import React, { useState, useRef, useEffect } from 'react';
import {
  Modal,
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  SafeAreaView,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Image,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { HubClient } from '../api/hubClient';
import { DoorEvent } from '../types/models';
import { SnapshotModal } from './SnapshotModal';

interface MessageMedia {
  event: DoorEvent;
  imageUrl: string;
  clipUrl?: string | null;
}

interface Message {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  toolUsed?: string;
  media?: MessageMedia[];
  timestamp: string;
}

interface AssistantModalProps {
  visible: boolean;
  onClose: () => void;
  onActionCompleted?: () => void;
}

const QUICK_PROMPTS = [
  { label: 'Security Briefing', query: 'Give me a security briefing' },
  { label: 'System Status', query: 'What is the system status?' },
  { label: 'Check Lock', query: 'Is the front door locked?' },
  { label: 'Turn On Lights', query: 'Turn on the lights' },
  { label: 'Recent Visitors', query: 'Did anyone come by today?' },
];

export const AssistantModal: React.FC<AssistantModalProps> = ({
  visible,
  onClose,
  onActionCompleted,
}) => {
  const [preview, setPreview] = useState<DoorEvent | null>(null);
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'welcome',
      sender: 'assistant',
      text: 'Hello! I am your Home AI Assistant, powered by Qwen 2.5 on the ROCK 5T NPU. How can I help you protect your home today?',
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    },
  ]);
  const [inputText, setInputText] = useState('');
  const [loading, setLoading] = useState(false);
  const flatListRef = useRef<FlatList>(null);

  useEffect(() => {
    if (visible) {
      setTimeout(() => {
        flatListRef.current?.scrollToEnd({ animated: true });
      }, 200);
    }
  }, [visible, messages]);

  const handleSend = async (queryText?: string) => {
    const textToSend = queryText || inputText.trim();
    if (!textToSend || loading) return;

    const userMsg: Message = {
      id: Date.now().toString(),
      sender: 'user',
      text: textToSend,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputText('');
    setLoading(true);

    try {
      const res = await HubClient.assistantChat(textToSend);
      const media: MessageMedia[] = [];
      for (const item of res.media) {
        const imageUrl = await HubClient.getEventSnapshotUrl(item.snapshotUrl);
        media.push({
          imageUrl,
          clipUrl: item.clipUrl,
          event: {
            id: item.id,
            ts: item.ts,
            label: item.label,
            confidence: 0,
            camera: item.camera,
            snapshotUrl: item.snapshotUrl,
          },
        });
      }
      const assistantMsg: Message = {
        id: (Date.now() + 1).toString(),
        sender: 'assistant',
        text: res.response,
        toolUsed: res.toolUsed,
        media,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      };
      setMessages((prev) => [...prev, assistantMsg]);
      onActionCompleted?.();
    } catch (err: any) {
      const errorMsg: Message = {
        id: (Date.now() + 1).toString(),
        sender: 'assistant',
        text: `Error connecting to Assistant: ${err?.message || 'Hub unavailable'}`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <SafeAreaView style={styles.container}>
        <View style={styles.header}>
          <View style={styles.headerTitleContainer}>
            <View style={styles.aiBadge}>
              <Ionicons name="sparkles" size={16} color="#38BDF8" />
            </View>
            <View>
              <Text style={styles.headerTitle}>Home AI Assistant</Text>
              <Text style={styles.headerSubtitle}>RKLLM Qwen2.5 on ROCK 5T NPU</Text>
            </View>
          </View>
          <TouchableOpacity style={styles.closeButton} onPress={onClose}>
            <Ionicons name="close" size={24} color="#FFF" />
          </TouchableOpacity>
        </View>

        <KeyboardAvoidingView
          style={styles.content}
          behavior={Platform.OS === 'ios' ? 'padding' : undefined}
          keyboardVerticalOffset={Platform.OS === 'ios' ? 10 : 0}
        >
          <FlatList
            ref={flatListRef}
            data={messages}
            keyExtractor={(item) => item.id}
            contentContainerStyle={styles.messageList}
            renderItem={({ item }) => (
              <View
                style={[
                  styles.messageBubble,
                  item.sender === 'user' ? styles.userBubble : styles.assistantBubble,
                ]}
              >
                {item.sender === 'assistant' && (
                  <View style={styles.assistantHeader}>
                    <Ionicons name="hardware-chip-outline" size={14} color="#38BDF8" />
                    <Text style={styles.assistantName}>Hub NPU</Text>
                    {item.toolUsed && item.toolUsed !== 'general_llm' && (
                      <View style={styles.toolTag}>
                        <Text style={styles.toolTagText}>Tool: {item.toolUsed}</Text>
                      </View>
                    )}
                  </View>
                )}
                <Text
                  style={[
                    styles.messageText,
                    item.sender === 'user' ? styles.userMessageText : styles.assistantMessageText,
                  ]}
                >
                  {item.text}
                </Text>
                {item.media && item.media.length > 0 && (
                  <View style={styles.thumbs}>
                    {item.media.map((shot: MessageMedia) => (
                      <TouchableOpacity
                        key={shot.event.id}
                        onPress={() => setPreview(shot.event)}
                        style={styles.thumbButton}
                      >
                        <Image source={{ uri: shot.imageUrl }} style={styles.thumb} />
                        {shot.clipUrl ? (
                          <View style={styles.playBadge}>
                            <Ionicons name="play" size={12} color="#FFF" />
                          </View>
                        ) : null}
                      </TouchableOpacity>
                    ))}
                  </View>
                )}
                <Text style={styles.timestamp}>{item.timestamp}</Text>
              </View>
            )}
            ListFooterComponent={
              loading ? (
                <View style={styles.thinkingBubble}>
                  <ActivityIndicator size="small" color="#38BDF8" />
                  <Text style={styles.thinkingText}>Edge NPU is processing...</Text>
                </View>
              ) : undefined
            }
          />

          <View style={styles.quickPromptsContainer}>
            <FlatList
              horizontal
              showsHorizontalScrollIndicator={false}
              data={QUICK_PROMPTS}
              keyExtractor={(item) => item.label}
              renderItem={({ item }) => (
                <TouchableOpacity
                  style={styles.quickPromptPill}
                  onPress={() => handleSend(item.query)}
                  disabled={loading}
                >
                  <Text style={styles.quickPromptText}>{item.label}</Text>
                </TouchableOpacity>
              )}
            />
          </View>

          <View style={styles.inputContainer}>
            <TextInput
              style={styles.input}
              value={inputText}
              onChangeText={setInputText}
              placeholder="Ask anything or command lights/lock..."
              placeholderTextColor="#64748B"
              returnKeyType="send"
              onSubmitEditing={() => handleSend()}
              editable={!loading}
            />
            <TouchableOpacity
              style={[
                styles.sendButton,
                (!inputText.trim() || loading) && styles.sendButtonDisabled,
              ]}
              onPress={() => handleSend()}
              disabled={!inputText.trim() || loading}
            >
              <Ionicons name="arrow-up" size={20} color="#FFF" />
            </TouchableOpacity>
          </View>
        </KeyboardAvoidingView>
        <SnapshotModal
          embedded
          visible={preview !== null}
          event={preview}
          onClose={() => setPreview(null)}
        />
      </SafeAreaView>
    </Modal>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0B0F19',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: '#1E293B',
  },
  headerTitleContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  aiBadge: {
    width: 38,
    height: 38,
    borderRadius: 12,
    backgroundColor: 'rgba(56, 189, 248, 0.15)',
    borderWidth: 1,
    borderColor: 'rgba(56, 189, 248, 0.3)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: '#F8FAFC',
  },
  headerSubtitle: {
    fontSize: 12,
    color: '#94A3B8',
  },
  closeButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#1E293B',
    alignItems: 'center',
    justifyContent: 'center',
  },
  content: {
    flex: 1,
  },
  messageList: {
    padding: 16,
    gap: 12,
  },
  messageBubble: {
    maxWidth: '85%',
    padding: 14,
    borderRadius: 18,
  },
  userBubble: {
    alignSelf: 'flex-end',
    backgroundColor: '#2563EB',
    borderBottomRightRadius: 4,
  },
  assistantBubble: {
    alignSelf: 'flex-start',
    backgroundColor: '#161E2E',
    borderWidth: 1,
    borderColor: '#1E293B',
    borderBottomLeftRadius: 4,
  },
  assistantHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginBottom: 6,
  },
  assistantName: {
    fontSize: 12,
    fontWeight: '600',
    color: '#38BDF8',
  },
  toolTag: {
    backgroundColor: 'rgba(56, 189, 248, 0.15)',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 6,
  },
  toolTagText: {
    fontSize: 10,
    color: '#7DD3FC',
    fontWeight: '600',
  },
  messageText: {
    fontSize: 15,
    lineHeight: 22,
  },
  userMessageText: {
    color: '#FFF',
  },
  assistantMessageText: {
    color: '#E2E8F0',
  },
  thumbs: {
    flexDirection: 'row',
    gap: 8,
    marginTop: 10,
  },
  thumbButton: {
    width: 84,
    height: 64,
    borderRadius: 8,
    overflow: 'hidden',
    backgroundColor: '#0F172A',
  },
  thumb: {
    width: 84,
    height: 64,
  },
  playBadge: {
    position: 'absolute',
    right: 4,
    bottom: 4,
    width: 18,
    height: 18,
    borderRadius: 9,
    backgroundColor: 'rgba(0, 0, 0, 0.65)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  timestamp: {
    fontSize: 10,
    color: '#64748B',
    alignSelf: 'flex-end',
    marginTop: 6,
  },
  thinkingBubble: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: '#161E2E',
    padding: 12,
    borderRadius: 16,
    alignSelf: 'flex-start',
    marginTop: 6,
    borderWidth: 1,
    borderColor: '#1E293B',
  },
  thinkingText: {
    fontSize: 13,
    color: '#94A3B8',
  },
  quickPromptsContainer: {
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderTopWidth: 1,
    borderTopColor: '#1E293B',
  },
  quickPromptPill: {
    backgroundColor: '#1E293B',
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 16,
    marginRight: 8,
    borderWidth: 1,
    borderColor: '#334155',
  },
  quickPromptText: {
    color: '#94A3B8',
    fontSize: 13,
    fontWeight: '500',
  },
  inputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: '#0F172A',
    borderTopWidth: 1,
    borderTopColor: '#1E293B',
    gap: 10,
  },
  input: {
    flex: 1,
    backgroundColor: '#161E2E',
    borderWidth: 1,
    borderColor: '#334155',
    borderRadius: 20,
    paddingHorizontal: 16,
    paddingVertical: 10,
    color: '#F8FAFC',
    fontSize: 15,
    maxHeight: 100,
  },
  sendButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: '#2563EB',
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendButtonDisabled: {
    opacity: 0.4,
    backgroundColor: '#334155',
  },
});
