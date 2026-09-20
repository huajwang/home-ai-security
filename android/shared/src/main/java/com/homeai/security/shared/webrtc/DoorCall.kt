package com.homeai.security.shared.webrtc

import android.content.Context
import android.media.AudioManager
import android.util.Log
import com.homeai.security.shared.api.HubClient
import org.webrtc.AudioSource
import org.webrtc.AudioTrack
import org.webrtc.DataChannel
import org.webrtc.DefaultVideoDecoderFactory
import org.webrtc.DefaultVideoEncoderFactory
import org.webrtc.EglBase
import org.webrtc.IceCandidate
import org.webrtc.MediaConstraints
import org.webrtc.MediaStream
import org.webrtc.MediaStreamTrack
import org.webrtc.PeerConnection
import org.webrtc.PeerConnectionFactory
import org.webrtc.RendererCommon
import org.webrtc.RtpReceiver
import org.webrtc.RtpTransceiver
import org.webrtc.SdpObserver
import org.webrtc.SessionDescription
import org.webrtc.SurfaceViewRenderer
import org.webrtc.VideoTrack
import org.webrtc.audio.JavaAudioDeviceModule
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

class DoorCall(
    private val context: Context,
    private val hub: HubClient,
    private val renderer: SurfaceViewRenderer
) {
    private val egl = EglBase.create()
    private val factory: PeerConnectionFactory
    private var peer: PeerConnection? = null
    private var audioSource: AudioSource? = null
    private var audioTrack: AudioTrack? = null
    private var audioDeviceModule: JavaAudioDeviceModule? = null
    private var callId: String? = null

    init {
        val options = PeerConnectionFactory.InitializationOptions.builder(context.applicationContext)
            .createInitializationOptions()
        PeerConnectionFactory.initialize(options)
        val adm = JavaAudioDeviceModule.builder(context.applicationContext)
            .setUseHardwareAcousticEchoCanceler(true)
            .setUseHardwareNoiseSuppressor(true)
            .createAudioDeviceModule()
        audioDeviceModule = adm
        factory = PeerConnectionFactory.builder()
            .setAudioDeviceModule(adm)
            .setVideoDecoderFactory(DefaultVideoDecoderFactory(egl.eglBaseContext))
            .setVideoEncoderFactory(DefaultVideoEncoderFactory(egl.eglBaseContext, true, true))
            .createPeerConnectionFactory()
        renderer.init(egl.eglBaseContext, null)
        renderer.setScalingType(
            RendererCommon.ScalingType.SCALE_ASPECT_FIT,
            RendererCommon.ScalingType.SCALE_ASPECT_FIT
        )
        renderer.setMirror(false)
    }

    fun start() {
        thread {
            try {
                startBlocking()
            } catch (ex: Exception) {
                Log.e(TAG, "call failed", ex)
            }
        }
    }

    private fun startBlocking() {
        val id = hub.createCall()
        callId = id
        val iceServers = emptyList<PeerConnection.IceServer>()
        val rtcConfig = PeerConnection.RTCConfiguration(iceServers)
        rtcConfig.sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
        rtcConfig.rtcpMuxPolicy = PeerConnection.RtcpMuxPolicy.REQUIRE
        peer = factory.createPeerConnection(rtcConfig, object : PeerConnection.Observer {
            override fun onIceCandidate(candidate: IceCandidate) {
                thread {
                    try {
                        hub.postIce(id, candidate.sdp, candidate.sdpMid, candidate.sdpMLineIndex)
                    } catch (ex: Exception) {
                        Log.w(TAG, "ice post failed", ex)
                    }
                }
            }

            override fun onAddStream(stream: MediaStream) {
                if (stream.videoTracks.isNotEmpty()) {
                    stream.videoTracks[0].addSink(renderer)
                }
            }

            override fun onAddTrack(receiver: RtpReceiver, streams: Array<out MediaStream>) {
                val track = receiver.track()
                if (track is VideoTrack) {
                    track.addSink(renderer)
                }
            }

            override fun onTrack(transceiver: RtpTransceiver) {
                val track = transceiver.receiver.track()
                if (track is VideoTrack) {
                    track.addSink(renderer)
                }
            }

            override fun onSignalingChange(state: PeerConnection.SignalingState) {}
            override fun onIceConnectionChange(state: PeerConnection.IceConnectionState) {
                Log.i(TAG, "ICE $state")
            }
            override fun onIceConnectionReceivingChange(receiving: Boolean) {}
            override fun onIceGatheringChange(state: PeerConnection.IceGatheringState) {
                Log.i(TAG, "ICE gathering $state")
            }
            override fun onIceCandidatesRemoved(candidates: Array<out IceCandidate>) {}
            override fun onRemoveStream(stream: MediaStream) {}
            override fun onDataChannel(channel: DataChannel) {}
            override fun onRenegotiationNeeded() {}
        })

        val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        audioManager.mode = AudioManager.MODE_IN_COMMUNICATION
        @Suppress("DEPRECATION")
        audioManager.isSpeakerphoneOn = true
        audioManager.isMicrophoneMute = false
        val sourceConstraints = MediaConstraints().apply {
            optional.add(MediaConstraints.KeyValuePair("googEchoCancellation", "true"))
            optional.add(MediaConstraints.KeyValuePair("googNoiseSuppression", "true"))
        }
        audioSource = factory.createAudioSource(sourceConstraints)
        audioTrack = factory.createAudioTrack("audio0", audioSource).also {
            it.setEnabled(true)
            it.setVolume(10.0)
        }
        peer?.addTrack(audioTrack)
        peer?.addTransceiver(
            MediaStreamTrack.MediaType.MEDIA_TYPE_VIDEO,
            RtpTransceiver.RtpTransceiverInit(RtpTransceiver.RtpTransceiverDirection.RECV_ONLY)
        )
        val offer = awaitSdp { observer -> peer?.createOffer(observer, MediaConstraints()) }
        awaitSet { observer -> peer?.setLocalDescription(observer, offer) }
        val (answerSdp, answerType) = hub.postOffer(id, offer.description)
        val answer = SessionDescription(
            if (answerType == "answer") SessionDescription.Type.ANSWER else SessionDescription.Type.PRANSWER,
            answerSdp
        )
        awaitSet { observer -> peer?.setRemoteDescription(observer, answer) }
    }

    fun hangup() {
        val id = callId
        callId = null
        peer?.close()
        peer = null
        audioTrack?.dispose()
        audioSource?.dispose()
        audioDeviceModule?.release()
        audioDeviceModule = null
        try {
            val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
            audioManager.mode = AudioManager.MODE_NORMAL
        } catch (_: Exception) {
        }
        if (id != null) {
            thread {
                try {
                    hub.hangup(id)
                } catch (_: Exception) {
                }
            }
        }
    }

    fun release() {
        hangup()
        renderer.release()
        factory.dispose()
        egl.release()
    }

    private fun awaitSdp(block: (SdpObserver) -> Unit): SessionDescription {
        val latch = CountDownLatch(1)
        var desc: SessionDescription? = null
        var error: String? = null
        block(object : SdpObserver {
            override fun onCreateSuccess(sdp: SessionDescription) {
                desc = sdp
                latch.countDown()
            }
            override fun onSetSuccess() { latch.countDown() }
            override fun onCreateFailure(p0: String?) { error = p0; latch.countDown() }
            override fun onSetFailure(p0: String?) { error = p0; latch.countDown() }
        })
        latch.await(8, TimeUnit.SECONDS)
        if (error != null) throw IllegalStateException(error)
        return desc ?: throw IllegalStateException("no SDP")
    }

    private fun awaitSet(block: (SdpObserver) -> Unit) {
        val latch = CountDownLatch(1)
        var error: String? = null
        block(object : SdpObserver {
            override fun onCreateSuccess(sdp: SessionDescription) {}
            override fun onSetSuccess() { latch.countDown() }
            override fun onCreateFailure(p0: String?) { error = p0; latch.countDown() }
            override fun onSetFailure(p0: String?) { error = p0; latch.countDown() }
        })
        latch.await(8, TimeUnit.SECONDS)
        if (error != null) throw IllegalStateException(error)
    }

    companion object {
        private const val TAG = "DoorCall"
    }
}
