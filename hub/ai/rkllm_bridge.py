"""RKLLM Python CTypes bridge for Qwen on RK3588 NPU."""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import queue
import threading
from typing import Callable, Generator, List, Optional

logger = logging.getLogger("home_ai.rkllm")

# RKLLM C Types definition
RKLLM_Handle_t = ctypes.c_void_p


class LLMCallState:
    RKLLM_RUN_NORMAL = 0
    RKLLM_RUN_WAITING = 1
    RKLLM_RUN_FINISH = 2
    RKLLM_RUN_ERROR = 3
    RKLLM_RUN_GET_LAST_HIDDEN_LAYER = 4


class RKLLMExtendParam(ctypes.Structure):
    _fields_ = [
        ("base_domain_id", ctypes.c_int32),
        ("embed_flash", ctypes.c_int8),
        ("enabled_cpus_num", ctypes.c_int8),
        ("enabled_cpus_mask", ctypes.c_uint32),
        ("n_batch", ctypes.c_uint8),
        ("use_cross_attn", ctypes.c_int8),
        ("reserved", ctypes.c_uint8 * 104),
    ]


class RKLLMParam(ctypes.Structure):
    _fields_ = [
        ("model_path", ctypes.c_char_p),
        ("max_context_len", ctypes.c_int32),
        ("max_new_tokens", ctypes.c_int32),
        ("top_k", ctypes.c_int32),
        ("n_keep", ctypes.c_int32),
        ("top_p", ctypes.c_float),
        ("temperature", ctypes.c_float),
        ("repeat_penalty", ctypes.c_float),
        ("frequency_penalty", ctypes.c_float),
        ("presence_penalty", ctypes.c_float),
        ("mirostat", ctypes.c_int32),
        ("mirostat_tau", ctypes.c_float),
        ("mirostat_eta", ctypes.c_float),
        ("skip_special_token", ctypes.c_bool),
        ("ignore_eos_token", ctypes.c_bool),
        ("is_async", ctypes.c_bool),
        ("extend_param", RKLLMExtendParam),
    ]


class RKLLMResultLastHiddenLayer(ctypes.Structure):
    _fields_ = [
        ("hidden_states", ctypes.POINTER(ctypes.c_float)),
        ("embd_size", ctypes.c_int),
        ("num_tokens", ctypes.c_int),
    ]


class RKLLMResultLogits(ctypes.Structure):
    _fields_ = [
        ("logits", ctypes.POINTER(ctypes.c_float)),
        ("vocab_size", ctypes.c_int),
        ("num_tokens", ctypes.c_int),
    ]


class RKLLMPerfStat(ctypes.Structure):
    _fields_ = [
        ("prefill_time_ms", ctypes.c_float),
        ("prefill_tokens", ctypes.c_int),
        ("generate_time_ms", ctypes.c_float),
        ("generate_tokens", ctypes.c_int),
        ("memory_usage_mb", ctypes.c_float),
    ]


class RKLLMResult(ctypes.Structure):
    _fields_ = [
        ("text", ctypes.c_char_p),
        ("token_id", ctypes.c_int),
        ("last_hidden_layer", RKLLMResultLastHiddenLayer),
        ("logits", RKLLMResultLogits),
        ("perf", RKLLMPerfStat),
    ]


class RKLLMInputUnion(ctypes.Union):
    _fields_ = [
        ("prompt_input", ctypes.c_char_p),
        ("embed_input", ctypes.c_void_p),
        ("token_input", ctypes.c_void_p),
        ("multimodal_input", ctypes.c_void_p),
    ]


class RKLLMInput(ctypes.Structure):
    _anonymous_ = ("input_data",)
    _fields_ = [
        ("role", ctypes.c_char_p),
        ("enable_thinking", ctypes.c_bool),
        ("input_type", ctypes.c_int),
        ("input_data", RKLLMInputUnion),
    ]


class RKLLMInferParam(ctypes.Structure):
    _fields_ = [
        ("mode", ctypes.c_int),
        ("lora_params", ctypes.c_void_p),
        ("prompt_cache_params", ctypes.c_void_p),
        ("sampling_params", ctypes.c_void_p),
        ("keep_history", ctypes.c_int),
        ("max_new_tokens", ctypes.c_int32),
    ]


LLMResultCallback_type = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.POINTER(RKLLMResult), ctypes.c_void_p, ctypes.c_int
)


class RKLLMCallback(ctypes.Structure):
    _fields_ = [
        ("result_callback", LLMResultCallback_type),
        ("result_userdata", ctypes.c_void_p),
        ("tokenizer_callback", ctypes.c_void_p),
        ("tokenizer_userdata", ctypes.c_void_p),
        ("embed_callback", ctypes.c_void_p),
        ("embed_userdata", ctypes.c_void_p),
    ]


def format_chatml(messages: list[dict[str, str]]) -> str:
    """Format a list of chat messages into Qwen ChatML prompt format."""
    prompt = ""
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        prompt += f"<|im_start|>{role}\n{content}<|im_end|>\n"
    prompt += "<|im_start|>assistant\n"
    return prompt


class RKLLMRunner:
    """Thread-safe runner for Qwen models via RKLLM on RK3588 NPU."""

    def __init__(
        self,
        model_path: str = "/home/radxa/rkllm/qwen2.5-0.5b.rkllm",
        lib_path: str = "librkllmrt.so",
        max_context_len: int = 2048,
        max_new_tokens: int = 512,
        auto_init: bool = True,
    ) -> None:
        self.model_path = model_path
        self.lib_path = lib_path
        self.max_context_len = max_context_len
        self.max_new_tokens = max_new_tokens
        self.handle: Optional[ctypes.c_void_p] = None
        self._rkllm_lib: Optional[ctypes.CDLL] = None
        self._lock = threading.Lock()
        self._is_available = False
        self._callback_holder: Optional[LLMResultCallback_type] = None
        self._cb_struct: Optional[RKLLMCallback] = None
        self._token_queue: queue.Queue[tuple[str, int]] = queue.Queue()

        if auto_init:
            self.initialize()

    @property
    def is_available(self) -> bool:
        return self._is_available and self.handle is not None and bool(self.handle.value)

    def initialize(self) -> bool:
        """Initialize librkllmrt library and load model into NPU."""
        with self._lock:
            if self.is_available:
                return True

            if not os.path.exists(self.model_path):
                logger.info(
                    "RKLLM model file not found at %s. NPU LLM disabled.",
                    self.model_path,
                )
                self._is_available = False
                return False

            try:
                self._rkllm_lib = ctypes.CDLL(self.lib_path)
            except Exception as exc:
                logger.info("Could not load %s (%s). NPU LLM disabled.", self.lib_path, exc)
                self._is_available = False
                return False

            try:
                # Set up C function prototypes
                self._rkllm_init = self._rkllm_lib.rkllm_init
                self._rkllm_init.argtypes = [
                    ctypes.POINTER(RKLLM_Handle_t),
                    ctypes.POINTER(RKLLMParam),
                    ctypes.POINTER(RKLLMCallback),
                ]
                self._rkllm_init.restype = ctypes.c_int

                self._rkllm_run = self._rkllm_lib.rkllm_run
                self._rkllm_run.argtypes = [
                    RKLLM_Handle_t,
                    ctypes.POINTER(RKLLMInput),
                    ctypes.POINTER(RKLLMInferParam),
                    ctypes.c_void_p,
                ]
                self._rkllm_run.restype = ctypes.c_int

                self._rkllm_destroy = self._rkllm_lib.rkllm_destroy
                self._rkllm_destroy.argtypes = [RKLLM_Handle_t]
                self._rkllm_destroy.restype = ctypes.c_int

                # Build callback
                def _c_callback(result_ptr, userdata, state):
                    text = ""
                    if result_ptr and result_ptr.contents.text:
                        try:
                            text = result_ptr.contents.text.decode("utf-8", errors="replace")
                        except Exception:
                            pass
                    self._token_queue.put((text, state))
                    return 0

                self._callback_holder = LLMResultCallback_type(_c_callback)
                self._cb_struct = RKLLMCallback()
                self._cb_struct.result_callback = self._callback_holder

                # Parameters
                handle = RKLLM_Handle_t()
                param = RKLLMParam()
                param.model_path = self.model_path.encode("utf-8")
                param.max_context_len = self.max_context_len
                param.max_new_tokens = self.max_new_tokens
                param.skip_special_token = True
                param.n_keep = -1
                param.top_k = 1
                param.top_p = 0.9
                param.temperature = 0.7
                param.repeat_penalty = 1.1
                param.is_async = False
                param.extend_param.base_domain_id = 0
                param.extend_param.embed_flash = 1
                param.extend_param.n_batch = 1
                param.extend_param.enabled_cpus_num = 4
                param.extend_param.enabled_cpus_mask = (1 << 4) | (1 << 5) | (1 << 6) | (1 << 7)

                ret = self._rkllm_init(
                    ctypes.byref(handle), ctypes.byref(param), ctypes.byref(self._cb_struct)
                )
                if ret != 0:
                    logger.error("rkllm_init failed with error code %d", ret)
                    self._is_available = False
                    return False

                self.handle = handle
                self._is_available = True
                logger.info("RKLLM model loaded successfully on RK3588 NPU: %s", self.model_path)
                return True
            except Exception as exc:
                logger.error("Failed to initialize RKLLM: %s", exc)
                self._is_available = False
                return False

    def stream_generate(
        self,
        prompt: str,
        max_new_tokens: int = 256,
        timeout: float = 30.0,
    ) -> Generator[str, None, None]:
        """Stream tokens generated from a prompt."""
        if not self.is_available:
            return

        with self._lock:
            # Clear queue
            while not self._token_queue.empty():
                try:
                    self._token_queue.get_nowait()
                except queue.Empty:
                    break

            inp = RKLLMInput()
            inp.role = b"user"
            inp.enable_thinking = False
            inp.input_type = 0
            inp.prompt_input = prompt.encode("utf-8")

            infer_param = RKLLMInferParam()
            infer_param.mode = 0
            infer_param.keep_history = 0
            infer_param.max_new_tokens = max_new_tokens

            ret = self._rkllm_run(
                self.handle, ctypes.byref(inp), ctypes.byref(infer_param), None
            )
            if ret != 0:
                logger.error("rkllm_run failed with code %d", ret)
                return

            # Read stream
            while True:
                try:
                    text, state = self._token_queue.get(timeout=timeout)
                except queue.Empty:
                    logger.warning("RKLLM generation timed out after %s seconds", timeout)
                    break

                if state == LLMCallState.RKLLM_RUN_NORMAL:
                    if text:
                        yield text
                elif state in (
                    LLMCallState.RKLLM_RUN_FINISH,
                    LLMCallState.RKLLM_RUN_ERROR,
                ):
                    if text:
                        yield text
                    break

    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 256,
        timeout: float = 30.0,
    ) -> str:
        """Synchronously generate full text from a prompt."""
        chunks = list(
            self.stream_generate(prompt=prompt, max_new_tokens=max_new_tokens, timeout=timeout)
        )
        return "".join(chunks).strip()

    def chat(
        self,
        messages: list[dict[str, str]],
        max_new_tokens: int = 256,
        timeout: float = 30.0,
    ) -> str:
        """Format chat messages and generate response."""
        prompt = format_chatml(messages)
        return self.generate(prompt=prompt, max_new_tokens=max_new_tokens, timeout=timeout)

    def close(self) -> None:
        """Unload model and free NPU resources."""
        with self._lock:
            if self.handle is not None and self.handle.value and self._rkllm_destroy:
                try:
                    self._rkllm_destroy(self.handle)
                except Exception as exc:
                    logger.warning("Error during rkllm_destroy: %s", exc)
            self.handle = None
            self._is_available = False
            logger.info("RKLLM model unloaded.")

    def __del__(self) -> None:
        self.close()


_RUNNER_INSTANCE: Optional[RKLLMRunner] = None
_RUNNER_LOCK = threading.Lock()


def get_runner(
    model_path: Optional[str] = None,
    lib_path: Optional[str] = None,
    auto_init: bool = True,
) -> RKLLMRunner:
    """Get or create singleton RKLLMRunner instance."""
    global _RUNNER_INSTANCE
    with _RUNNER_LOCK:
        if _RUNNER_INSTANCE is None:
            from hub.config import RKLLM_LIB_PATH, RKLLM_MODEL_PATH

            m_path = model_path or RKLLM_MODEL_PATH
            l_path = lib_path or RKLLM_LIB_PATH
            _RUNNER_INSTANCE = RKLLMRunner(
                model_path=m_path,
                lib_path=l_path,
                auto_init=auto_init,
            )
        return _RUNNER_INSTANCE
