/**
 * API 客户端
 * 统一的错误处理和错误提示
 */
import axios, { AxiosInstance, AxiosRequestConfig, AxiosResponse, AxiosError } from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

const baseURL = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

// 错误类型定义
interface ApiError {
  status: number
  message: string
  detail?: string | Record<string, any>
  rate_limit?: {
    limit: number
    remaining: number
    reset: number
    type: string
  }
}

// 错误码映射
const ERROR_MESSAGES: Record<number, string> = {
  400: '请求参数错误',
  401: '登录已过期，请重新登录',
  403: '没有权限执行此操作',
  404: '请求的资源不存在',
  408: '请求超时，请重试',
  422: '数据验证失败',
  429: '请求过于频繁，请稍后再试',
  500: '服务器内部错误',
  502: '网关错误',
  503: '服务暂时不可用',
  504: '网关超时',
}

// 获取错误消息
function getErrorMessage(error: AxiosError<ApiError>): string {
  const status = error.response?.status
  const data = error.response?.data
  
  // 优先使用后端返回的detail
  if (data?.detail) {
    if (typeof data.detail === 'string') {
      return data.detail
    }
    // 如果是对象，尝试提取第一个错误消息
    if (typeof data.detail === 'object') {
      const firstKey = Object.keys(data.detail)[0]
      if (firstKey && Array.isArray(data.detail[firstKey])) {
        return `${firstKey}: ${data.detail[firstKey][0]}`
      }
    }
  }
  
  // 使用预设错误消息
  if (status && ERROR_MESSAGES[status]) {
    return ERROR_MESSAGES[status]
  }
  
  // 网络错误
  if (!error.response) {
    if (error.code === 'ECONNABORTED') {
      return '请求超时，请检查网络后重试'
    }
    return '网络连接失败，请检查网络'
  }
  
  return '请求失败，请稍后重试'
}

const apiClient: AxiosInstance = axios.create({
  baseURL: `${baseURL}/api/v1`,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
apiClient.interceptors.response.use(
  (response: AxiosResponse) => {
    return response.data
  },
  async (error: AxiosError<ApiError>) => {
    const status = error.response?.status
    const data = error.response?.data
    
    // 获取错误消息
    const message = getErrorMessage(error)
    
    // 处理429限流错误 - 显示详细重置时间
    if (status === 429 && data?.rate_limit) {
      const { reset, type } = data.rate_limit
      ElMessage.error({
        message: `${message} (${type}限流 ${reset}秒后重置)`,
        duration: 5000,
      })
    } else if (status === 401) {
      // 401错误 - 清除token并跳转登录
      ElMessage.error(message)
      localStorage.removeItem('token')
      // 延迟跳转，让用户看到错误消息
      setTimeout(() => {
        window.location.href = '/login'
      }, 1500)
    } else if (status === 403) {
      // 403错误 - 显示错误，可能需要管理员权限
      ElMessage.error(message)
    } else if (status && status >= 500) {
      // 5xx错误 - 服务器错误
      ElMessage.error(message)
    } else if (status && status >= 400) {
      // 4xx错误 - 客户端错误
      ElMessage.warning(message)
    } else {
      // 网络错误
      ElMessage.error(message)
    }
    
    return Promise.reject(error)
  }
)

export default apiClient

// ============ API 接口 ============

// 认证
export const authApi = {
  login: (username: string, password: string) => 
    apiClient.post('/auth/login', null, { params: { username, password } }),
  
  register: (data: { username: string; email: string; password: string }) =>
    apiClient.post('/auth/register', data),
  
  logout: () => apiClient.post('/auth/logout'),
  
  getCurrentUser: () => apiClient.get('/auth/me'),
  
  updateUser: (data: any) => apiClient.put('/auth/me', data),
}

// 饰品
export const itemsApi = {
  list: (params: any) => apiClient.get('/items', { params }),
  
  search: (keyword: string) => apiClient.get('/items/search', { params: { keyword } }),
  
  get: (id: number) => apiClient.get(`/items/${id}`),
  
  getPriceHistory: (id: number, params: { source?: string; days?: number }) => 
    apiClient.get(`/items/${id}/price`, { params }),
  
  getOverview: (id: number) => apiClient.get(`/items/${id}/overview`),
}

// 订单
export const ordersApi = {
  list: (params: any) => apiClient.get('/orders', { params }),
  
  create: (data: any) => apiClient.post('/orders', data),
  
  get: (id: string) => apiClient.get(`/orders/${id}`),
  
  cancel: (id: string) => apiClient.delete(`/orders/${id}`),
}

// 库存
export const inventoryApi = {
  list: (params: any) => apiClient.get('/inventory', { params }),
  
  listItem: (id: number) => apiClient.get(`/inventory/${id}`),
  
  listOnMarket: (id: number, data: { price: number }) => 
    apiClient.post(`/inventory/${id}/list`, data),
  
  unlist: (id: number) => apiClient.post(`/inventory/${id}/unlist`),
}

// 监控
export const monitorsApi = {
  list: () => apiClient.get('/monitors'),
  
  create: (data: any) => apiClient.post('/monitors', data),
  
  update: (id: number, data: any) => apiClient.put(`/monitors/${id}`, data),
  
  delete: (id: number) => apiClient.delete(`/monitors/${id}`),
  
  getLogs: (id: number) => apiClient.get(`/monitors/${id}/logs`),
}

// 机器人
export const botsApi = {
  list: () => apiClient.get('/bots'),
  
  create: (data: any) => apiClient.post('/bots', data),
  
  update: (id: number, data: any) => apiClient.put(`/bots/${id}`, data),
  
  delete: (id: number) => apiClient.delete(`/bots/${id}`),
  
  login: (id: number) => apiClient.post(`/bots/${id}/login`),
  
  trade: (id: number, data: any) => apiClient.post(`/bots/${id}/trade`, data),
}

// 统计
export const statsApi = {
  dashboard: () => apiClient.get('/stats/dashboard'),
  
  profit: (params: any) => apiClient.get('/stats/profit', { params }),
  
  tradeVolume: (params: any) => apiClient.get('/stats/trade-volume', { params }),
}
