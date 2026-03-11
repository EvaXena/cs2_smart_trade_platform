/**
 * WebSocket 客户端
 * 支持断线自动重连、心跳机制
 * 与后端 /ws/notifications 端点对接
 */
import { ref, readonly } from 'vue'
import { ElNotification } from 'element-plus'
import { useUserStore } from '@/stores/user'

// WebSocket 配置
const WS_CONFIG = {
  // 重连配置
  RECONNECT_BASE_DELAY: 1000,    // 基础重连延迟(ms)
  RECONNECT_MAX_DELAY: 30000,   // 最大重连延迟(ms)
  RECONNECT_MAX_RETRIES: 10,    // 最大重试次数
  
  // 心跳配置
  HEARTBEAT_INTERVAL: 30000,    // 心跳间隔(ms)
  HEARTBEAT_TIMEOUT: 10000,     // 心跳超时(ms)
  
  // 连接配置
  CONNECT_TIMEOUT: 10000,       // 连接超时(ms)
}

// 消息类型定义
export interface WSMessage {
  type: string
  [key: string]: any
}

export interface NotificationMessage {
  id: number
  notification_type: string
  priority: string
  title: string
  content: string
  data: Record<string, any> | null
  created_at: string
}

// 连接状态
export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'reconnecting' | 'error'

// WebSocket客户端类
class WebSocketClient {
  private ws: WebSocket | null = null
  private status: ConnectionStatus = 'disconnected'
  private statusRef = ref<ConnectionStatus>('disconnected')
  
  // 重连相关
  private reconnectAttempts = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  
  // 心跳相关
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null
  private heartbeatTimeoutTimer: ReturnType<typeof setTimeout> | null = null
  
  // 消息队列（重连期间缓存）
  private messageQueue: WSMessage[] = []
  
  // 消息处理器
  private handlers: Map<string, ((data: any) => void)[]> = new Map()
  
  // 通知回调
  private notificationCallback: ((notification: NotificationMessage) => void) | null = null
  
  constructor() {
    // 定期检查连接状态
    this.startStatusCheck()
  }
  
  /**
   * 获取当前连接状态
   */
  getStatus(): ConnectionStatus {
    return this.status
  }
  
  /**
   * 获取状态（响应式）
   */
  getStatusRef() {
    return readonly(this.statusRef)
  }
  
  /**
   * 更新状态
   */
  private setStatus(status: ConnectionStatus) {
    this.status = status
    this.statusRef.value = status
  }
  
  /**
   * 连接WebSocket
   */
  async connect(token?: string): Promise<boolean> {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      console.warn('[WS] Already connected')
      return true
    }
    
    // 获取token
    const userStore = useUserStore()
    const wsToken = token || userStore.token
    
    if (!wsToken) {
      console.error('[WS] No authentication token available')
      this.setStatus('error')
      return false
    }
    
    this.setStatus('connecting')
    
    // 构建WebSocket URL
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = import.meta.env.VITE_WS_URL || `${protocol}//${window.location.host}`
    const wsUrl = `${host}/ws/notifications?token=${wsToken}`
    
    try {
      this.ws = new WebSocket(wsUrl)
      
      // 设置连接超时
      const connectTimeoutPromise = new Promise<boolean>((_, reject) => {
        setTimeout(() => reject(new Error('Connection timeout')), WS_CONFIG.CONNECT_TIMEOUT)
      })
      
      const openPromise = new Promise<boolean>((resolve) => {
        this.ws!.onopen = () => {
          console.log('[WS] Connected successfully')
          this.setStatus('connected')
          this.reconnectAttempts = 0
          resolve(true)
        }
      })
      
      await Promise.race([openPromise, connectTimeoutPromise])
      
      // 设置事件处理器
      this.setupEventHandlers()
      
      // 启动心跳
      this.startHeartbeat()
      
      // 发送缓存的消息
      this.flushMessageQueue()
      
      return true
    } catch (error) {
      console.error('[WS] Connection failed:', error)
      this.setStatus('error')
      this.scheduleReconnect()
      return false
    }
  }
  
  /**
   * 断开连接
   */
  disconnect() {
    this.stopHeartbeat()
    this.cancelReconnect()
    
    if (this.ws) {
      this.ws.onclose = null
      this.ws.close()
      this.ws = null
    }
    
    this.setStatus('disconnected')
    console.log('[WS] Disconnected')
  }
  
  /**
   * 发送消息
   */
  send(message: WSMessage): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      // 缓存消息，稍后发送
      this.messageQueue.push(message)
      console.warn('[WS] Not connected, message queued')
      return false
    }
    
    try {
      this.ws.send(JSON.stringify(message))
      return true
    } catch (error) {
      console.error('[WS] Send failed:', error)
      return false
    }
  }
  
  /**
   * 发送心跳
   */
  private sendHeartbeat() {
    this.send({ type: 'heartbeat' })
    
    // 设置心跳超时
    this.heartbeatTimeoutTimer = setTimeout(() => {
      console.warn('[WS] Heartbeat timeout')
      this.handleDisconnect()
    }, WS_CONFIG.HEARTBEAT_TIMEOUT)
  }
  
  /**
   * 启动心跳
   */
  private startHeartbeat() {
    this.stopHeartbeat()
    this.heartbeatTimer = setInterval(() => {
      if (this.status === 'connected') {
        this.sendHeartbeat()
      }
    }, WS_CONFIG.HEARTBEAT_INTERVAL)
  }
  
  /**
   * 停止心跳
   */
  private stopHeartbeat() {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
    if (this.heartbeatTimeoutTimer) {
      clearTimeout(this.heartbeatTimeoutTimer)
      this.heartbeatTimeoutTimer = null
    }
  }
  
  /**
   * 设置事件处理器
   */
  private setupEventHandlers() {
    if (!this.ws) return
    
    this.ws.onmessage = (event) => {
      try {
        const message: WSMessage = JSON.parse(event.data)
        this.handleMessage(message)
      } catch (error) {
        console.error('[WS] Failed to parse message:', error)
      }
    }
    
    this.ws.onerror = (error) => {
      console.error('[WS] Error:', error)
    }
    
    this.ws.onclose = () => {
      console.log('[WS] Connection closed')
      this.handleDisconnect()
    }
  }
  
  /**
   * 处理收到的消息
   */
  private handleMessage(message: WSMessage) {
    console.log('[WS] Received:', message.type, message)
    
    // 清除心跳超时
    if (this.heartbeatTimeoutTimer) {
      clearTimeout(this.heartbeatTimeoutTimer)
      this.heartbeatTimeoutTimer = null
    }
    
    // 根据消息类型分发
    switch (message.type) {
      case 'notification_connected':
        console.log('[WS] Notification channel ready')
        break
        
      case 'notification':
        // 收到新通知
        if (this.notificationCallback && message.data) {
          this.notificationCallback(message.data as NotificationMessage)
        }
        // 显示通知
        this.showNotification(message.data as NotificationMessage)
        break
        
      case 'pong':
      case 'heartbeat_ack':
        // 心跳响应
        break
        
      case 'token_expiring':
        // Token即将过期
        console.warn('[WS] Token expiring:', message.expires_in)
        this.handleTokenExpiring(message.expires_in)
        break
        
      case 'error':
        console.error('[WS] Server error:', message.message)
        break
        
      default:
        // 触发自定义处理器
        const handlers = this.handlers.get(message.type)
        if (handlers) {
          handlers.forEach(handler => handler(message))
        }
    }
  }
  
  /**
   * 处理连接断开
   */
  private handleDisconnect() {
    this.stopHeartbeat()
    this.setStatus('disconnected')
    this.scheduleReconnect()
  }
  
  /**
   * 安排重连（指数退避）
   */
  private scheduleReconnect() {
    if (this.reconnectAttempts >= WS_CONFIG.RECONNECT_MAX_RETRIES) {
      console.error('[WS] Max reconnection attempts reached')
      ElNotification.error({
        title: '连接失败',
        message: '无法建立WebSocket连接，请刷新页面重试',
        duration: 0
      })
      return
    }
    
    // 指数退避计算
    const delay = Math.min(
      WS_CONFIG.RECONNECT_BASE_DELAY * Math.pow(2, this.reconnectAttempts),
      WS_CONFIG.RECONNECT_MAX_DELAY
    )
    
    console.log(`[WS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts + 1})`)
    this.setStatus('reconnecting')
    
    this.reconnectTimer = setTimeout(() => {
      this.reconnectAttempts++
      this.connect()
    }, delay)
  }
  
  /**
   * 取消重连
   */
  private cancelReconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }
  
  /**
   * 刷新消息队列
   */
  private flushMessageQueue() {
    if (this.messageQueue.length === 0) return
    
    console.log(`[WS] Flushing ${this.messageQueue.length} queued messages`)
    const queue = [...this.messageQueue]
    this.messageQueue = []
    
    queue.forEach(msg => this.send(msg))
  }
  
  /**
   * 显示通知
   */
  private showNotification(notification: NotificationMessage) {
    const typeMap: Record<string, 'success' | 'warning' | 'error' | 'info'> = {
      'success': 'success',
      'warning': 'warning',
      'error': 'error',
      'system': 'info',
      'trade': 'success',
      'price_alert': 'warning'
    }
    
    const notificationType = typeMap[notification.notification_type] || 'info'
    
    ElNotification({
      title: notification.title,
      message: notification.content,
      type: notificationType,
      duration: 5000
    })
  }
  
  /**
   * 处理Token即将过期
   */
  private handleTokenExpiring(expiresIn: number) {
    // 可以触发token刷新
    console.log('[WS] Token will expire in', expiresIn, 'seconds')
  }
  
  /**
   * 注册消息处理器
   */
  on(type: string, handler: (data: any) => void) {
    if (!this.handlers.has(type)) {
      this.handlers.set(type, [])
    }
    this.handlers.get(type)!.push(handler)
  }
  
  /**
   * 移除消息处理器
   */
  off(type: string, handler?: (data: any) => void) {
    if (!handler) {
      this.handlers.delete(type)
      return
    }
    
    const handlers = this.handlers.get(type)
    if (handlers) {
      const index = handlers.indexOf(handler)
      if (index > -1) {
        handlers.splice(index, 1)
      }
    }
  }
  
  /**
   * 设置通知回调
   */
  onNotification(callback: (notification: NotificationMessage) => void) {
    this.notificationCallback = callback
  }
  
  /**
   * 定期检查连接状态
   */
  private startStatusCheck() {
    setInterval(() => {
      if (this.status === 'connected' && this.ws?.readyState !== WebSocket.OPEN) {
        console.warn('[WS] Connection lost detected')
        this.handleDisconnect()
      }
    }, 5000)
  }
}

// 创建单例
const wsClient = new WebSocketClient()

// Vue 组合式函数
export function useWebSocket() {
  return {
    // 状态
    status: wsClient.getStatusRef(),
    
    // 方法
    connect: (token?: string) => wsClient.connect(token),
    disconnect: () => wsClient.disconnect(),
    send: (message: WSMessage) => wsClient.send(message),
    on: (type: string, handler: (data: any) => void) => wsClient.on(type, handler),
    off: (type: string, handler?: (data: any) => void) => wsClient.off(type, handler),
    onNotification: (callback: (notification: NotificationMessage) => void) => wsClient.onNotification(callback),
  }
}

export default wsClient
