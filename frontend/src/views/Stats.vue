<template>
  <div class="stats-page">
    <div class="page-header">
      <h1>数据统计</h1>
      <div class="header-actions">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          @change="handleDateChange"
        />
      </div>
    </div>

    <!-- 概览卡片 -->
    <el-row :gutter="20" class="overview-cards">
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-icon" style="background: #409eff;">
              <el-icon><User /></el-icon>
            </div>
            <div class="stat-content">
              <div class="stat-label">用户数</div>
              <div class="stat-value">{{ overviewStats.total_users }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-icon" style="background: #67c23a;">
              <el-icon><Connection /></el-icon>
            </div>
            <div class="stat-content">
              <div class="stat-label">机器人</div>
              <div class="stat-value">{{ overviewStats.total_bots }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-icon" style="background: #e6a23c;">
              <el-icon><ShoppingCart /></el-icon>
            </div>
            <div class="stat-content">
              <div class="stat-label">订单数</div>
              <div class="stat-value">{{ overviewStats.total_orders }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-icon" style="background: #f56c6c;">
              <el-icon><Coin /></el-icon>
            </div>
            <div class="stat-content">
              <div class="stat-label">交易总额</div>
              <div class="stat-value">¥{{ formatNumber(overviewStats.total_volume) }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 统计图表区域 -->
    <el-row :gutter="20">
      <!-- 交易趋势 -->
      <el-col :span="12">
        <el-card class="chart-card">
          <template #header>
            <div class="card-header">
              <span>交易趋势</span>
              <el-radio-group v-model="trendPeriod" size="small" @change="fetchTrendData">
                <el-radio-button label="7">7天</el-radio-button>
                <el-radio-button label="30">30天</el-radio-button>
                <el-radio-button label="90">90天</el-radio-button>
              </el-radio-group>
            </div>
          </template>
          <div ref="tradeChartRef" class="chart-container"></div>
        </el-card>
      </el-col>

      <!-- 利润趋势 -->
      <el-col :span="12">
        <el-card class="chart-card">
          <template #header>
            <div class="card-header">
              <span>利润趋势</span>
              <el-radio-group v-model="profitPeriod" size="small" @change="fetchProfitData">
                <el-radio-button label="daily">日</el-radio-button>
                <el-radio-button label="weekly">周</el-radio-button>
                <el-radio-button label="monthly">月</el-radio-button>
              </el-radio-group>
            </div>
          </template>
          <div ref="profitChartRef" class="chart-container"></div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 库存分布 -->
    <el-row :gutter="20" style="margin-top: 20px;">
      <el-col :span="12">
        <el-card class="chart-card">
          <template #header>
            <div class="card-header">
              <span>库存分布</span>
            </div>
          </template>
          <div ref="inventoryChartRef" class="chart-container"></div>
        </el-card>
      </el-col>
      
      <!-- 交易类型分布 -->
      <el-col :span="12">
        <el-card class="chart-card">
          <template #header>
            <div class="card-header">
              <span>交易类型分布</span>
            </div>
          </template>
          <div ref="tradeTypeChartRef" class="chart-container"></div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 详细数据 -->
    <el-row :gutter="20" style="margin-top: 20px;">
      <!-- 利润统计 -->
      <el-col :span="12">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>利润统计</span>
            </div>
          </template>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="今日利润">
              <span class="profit-text" :class="{ negative: profitStats.daily?.total_profit < 0 }">
                ¥{{ formatNumber(profitStats.daily?.total_profit || 0) }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="本周利润">
              <span class="profit-text" :class="{ negative: profitStats.weekly?.total_profit < 0 }">
                ¥{{ formatNumber(profitStats.weekly?.total_profit || 0) }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="本月利润">
              <span class="profit-text" :class="{ negative: profitStats.monthly?.total_profit < 0 }">
                ¥{{ formatNumber(profitStats.monthly?.total_profit || 0) }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="累计利润">
              <span class="profit-text" :class="{ negative: profitStats.all_time?.total_profit < 0 }">
                ¥{{ formatNumber(profitStats.all_time?.total_profit || 0) }}
              </span>
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>

      <!-- 库存价值 -->
      <el-col :span="12">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>库存价值</span>
            </div>
          </template>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="总价值">
              <span class="value-text">¥{{ formatNumber(inventoryValue.total_value) }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="Steam 库存">
              <span>¥{{ formatNumber(inventoryValue.by_platform?.steam || 0) }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="BUFF 库存">
              <span>¥{{ formatNumber(inventoryValue.by_platform?.buff || 0) }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="物品数量">
              <span>{{ inventoryValue.top_items?.length || 0 }} 种</span>
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
    </el-row>

    <!-- 最近交易 -->
    <el-card style="margin-top: 20px;">
      <template #header>
        <div class="card-header">
          <span>最近交易</span>
          <el-button type="primary" size="small" @click="fetchRecentTrades">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </template>
      <el-table :data="recentTrades" v-loading="loading">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="trade_offer_id" label="交易号" width="150" />
        <el-table-column prop="direction" label="方向" width="100">
          <template #default="{ row }">
            <el-tag :type="row.direction === 'incoming' ? 'success' : 'warning'">
              {{ row.direction === 'incoming' ? '接收' : '发送' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getTradeStatusType(row.status)">
              {{ getTradeStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="180" />
        <el-table-column prop="accepted_at" label="完成时间" width="180" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { User, Connection, ShoppingCart, Coin, Refresh } from '@element-plus/icons-vue'
import * as echarts from 'echarts'

const loading = ref(false)
const dateRange = ref<[Date, Date] | null>(null)
const trendPeriod = ref('7')
const profitPeriod = ref('daily')

// Chart refs
const tradeChartRef = ref<HTMLElement>()
const profitChartRef = ref<HTMLElement>()
const inventoryChartRef = ref<HTMLElement>()
const tradeTypeChartRef = ref<HTMLElement>()

// Chart instances
let tradeChart: echarts.ECharts | null = null
let profitChart: echarts.ECharts | null = null
let inventoryChart: echarts.ECharts | null = null
let tradeTypeChart: echarts.ECharts | null = null

const overviewStats = ref({
  total_users: 0,
  total_bots: 0,
  total_orders: 0,
  total_trades: 0,
  total_volume: 0,
  active_monitors: 0,
  inventory_value: 0
})

const profitStats = ref<any>({})
const inventoryValue = ref<{
  total_value: number;
  by_platform: Record<string, number>;
  by_rarity: Record<string, number>;
  top_items: Array<{ name: string; value: number }>;
}>({
  total_value: 0,
  by_platform: {},
  by_rarity: {},
  top_items: []
})

const recentTrades = ref([])

// 格式化数字
const formatNumber = (num: number | undefined | null) => {
  if (num === undefined || num === null) return '0.00'
  return new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(num)
}

const getTradeStatusType = (status: string) => {
  const types: Record<string, string> = {
    pending: 'warning',
    accepted: 'success',
    declined: 'danger',
    cancelled: 'info'
  }
  return types[status] || 'info'
}

const getTradeStatusText = (status: string) => {
  const texts: Record<string, string> = {
    pending: '待处理',
    accepted: '已接受',
    declined: '已拒绝',
    cancelled: '已取消'
  }
  return texts[status] || status
}

// 获取概览统计
const fetchOverviewStats = async () => {
  try {
    const token = localStorage.getItem('token')
    const response = await fetch('/api/v1/stats', {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
    const data = await response.json()
    overviewStats.value = data
  } catch (error) {
    console.error('获取概览统计失败', error)
    ElMessage.error('获取概览统计失败，请稍后重试')
  }
}

// 获取利润统计
const fetchProfitStats = async () => {
  try {
    const token = localStorage.getItem('token')
    const response = await fetch('/api/v1/stats/profit', {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
    const data = await response.json()
    profitStats.value = data
    updateProfitChart()
  } catch (error) {
    console.error('获取利润统计失败', error)
    ElMessage.error('获取利润统计失败，请稍后重试')
  }
}

// 获取库存价值
const fetchInventoryValue = async () => {
  try {
    const token = localStorage.getItem('token')
    const response = await fetch('/api/v1/stats/inventory_value', {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
    const data = await response.json()
    inventoryValue.value = data
    updateInventoryChart()
  } catch (error) {
    console.error('获取库存价值失败', error)
    ElMessage.error('获取库存价值失败，请稍后重试')
  }
}

// 获取最近交易
const fetchRecentTrades = async () => {
  loading.value = true
  try {
    const token = localStorage.getItem('token')
    const response = await fetch('/api/v1/stats/trades?days=7', {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
    const data = await response.json()
    recentTrades.value = data.trades || []
    updateTradeTypeChart()
  } catch (error) {
    console.error('获取最近交易失败', error)
    ElMessage.error('获取最近交易失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

// 获取趋势数据
const fetchTrendData = async () => {
  if (!tradeChart) return
  
  try {
    const token = localStorage.getItem('token')
    const response = await fetch(`/api/v1/stats/trades?days=${trendPeriod.value}`, {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
    const data = await response.json()
    
    // 生成模拟数据用于展示
    const dates = []
    const volumes = []
    const counts = []
    
    for (let i = parseInt(trendPeriod.value) - 1; i >= 0; i--) {
      const date = new Date()
      date.setDate(date.getDate() - i)
      dates.push(date.toLocaleDateString('zh-CN'))
      volumes.push(Math.random() * 10000 + 1000)
      counts.push(Math.floor(Math.random() * 50 + 10))
    }
    
    tradeChart.setOption({
      tooltip: {
        trigger: 'axis'
      },
      legend: {
        data: ['交易额', '交易数']
      },
      xAxis: {
        type: 'category',
        data: dates
      },
      yAxis: [
        { type: 'value', name: '交易额(¥)' },
        { type: 'value', name: '交易数' }
      ],
      series: [
        {
          name: '交易额',
          type: 'bar',
          data: volumes,
          itemStyle: { color: '#409eff' }
        },
        {
          name: '交易数',
          type: 'line',
          yAxisIndex: 1,
          data: counts,
          itemStyle: { color: '#67c23a' }
        }
      ]
    })
  } catch (error) {
    console.error('获取趋势数据失败', error)
    ElMessage.error('获取趋势数据失败，请稍后重试')
  }
}

// 获取利润数据
const fetchProfitData = async () => {
  updateProfitChart()
}

// 更新利润图表
const updateProfitChart = () => {
  if (!profitChart) return
  
  const periods = ['daily', 'weekly', 'monthly', 'all_time']
  const labels = ['今日', '本周', '本月', '累计']
  const profits = periods.map(p => profitStats.value[p]?.total_profit || 0)
  const fees = periods.map(p => profitStats.value[p]?.fee || 0)
  
  profitChart.setOption({
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        let result = params[0].name + '<br/>'
        params.forEach((item: any) => {
          result += item.marker + ' ' + item.seriesName + ': ¥' + item.value.toFixed(2) + '<br/>'
        })
        return result
      }
    },
    legend: {
      data: ['净利润', '手续费']
    },
    xAxis: {
      type: 'category',
      data: labels
    },
    yAxis: {
      type: 'value',
      name: '金额(¥)'
    },
    series: [
      {
        name: '净利润',
        type: 'bar',
        data: profits.map(v => v >= 0 ? v : 0),
        itemStyle: { color: '#67c23a' }
      },
      {
        name: '手续费',
        type: 'bar',
        data: fees,
        itemStyle: { color: '#f56c6c' }
      }
    ]
  })
}

// 更新库存图表
const updateInventoryChart = () => {
  if (!inventoryChart) return
  
  const platformData = [
    { value: inventoryValue.value.by_platform?.steam || 0, name: 'Steam' },
    { value: inventoryValue.value.by_platform?.buff || 0, name: 'BUFF' }
  ]
  
  inventoryChart.setOption({
    tooltip: {
      trigger: 'item',
      formatter: '{b}: ¥{c} ({d}%)'
    },
    legend: {
      orient: 'vertical',
      left: 'left'
    },
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        avoidLabelOverlap: false,
        itemStyle: {
          borderRadius: 10,
          borderColor: '#fff',
          borderWidth: 2
        },
        label: {
          show: true,
          formatter: '¥{c}'
        },
        data: platformData
      }
    ]
  })
}

// 更新交易类型图表
const updateTradeTypeChart = () => {
  if (!tradeTypeChart) return
  
  const total = recentTrades.value.length || 1
  const incoming = recentTrades.value.filter((t: any) => t.direction === 'incoming').length
  const outgoing = total - incoming
  
  tradeTypeChart.setOption({
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c} ({d}%)'
    },
    legend: {
      orient: 'vertical',
      left: 'left'
    },
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        avoidLabelOverlap: false,
        itemStyle: {
          borderRadius: 10,
          borderColor: '#fff',
          borderWidth: 2
        },
        label: {
          show: true,
          formatter: '{c}'
        },
        data: [
          { value: incoming, name: '接收', itemStyle: { color: '#67c23a' } },
          { value: outgoing, name: '发送', itemStyle: { color: '#e6a23c' } }
        ]
      }
    ]
  })
}

// 初始化图表
const initCharts = async () => {
  await nextTick()
  
  if (tradeChartRef.value) {
    tradeChart = echarts.init(tradeChartRef.value)
    fetchTrendData()
  }
  
  if (profitChartRef.value) {
    profitChart = echarts.init(profitChartRef.value)
    updateProfitChart()
  }
  
  if (inventoryChartRef.value) {
    inventoryChart = echarts.init(inventoryChartRef.value)
    updateInventoryChart()
  }
  
  if (tradeTypeChartRef.value) {
    tradeTypeChart = echarts.init(tradeTypeChartRef.value)
    updateTradeTypeChart()
  }
  
  // 响应窗口大小变化
  window.addEventListener('resize', handleResize)
}

const handleResize = () => {
  tradeChart?.resize()
  profitChart?.resize()
  inventoryChart?.resize()
  tradeTypeChart?.resize()
}

const handleDateChange = () => {
  fetchOverviewStats()
  fetchProfitStats()
}

onMounted(async () => {
  await fetchOverviewStats()
  await fetchProfitStats()
  await fetchInventoryValue()
  await fetchRecentTrades()
  await initCharts()
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  tradeChart?.dispose()
  profitChart?.dispose()
  inventoryChart?.dispose()
  tradeTypeChart?.dispose()
})
</script>

<style scoped>
.stats-page {
  padding: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 15px;
}

.page-header h1 {
  margin: 0;
  font-size: 24px;
}

.page-header .header-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.overview-cards {
  margin-bottom: 20px;
}

.overview-cards :deep(.el-row) {
  margin-left: -10px !important;
  margin-right: -10px !important;
}

.overview-cards :deep(.el-col) {
  padding-left: 10px !important;
  padding-right: 10px !important;
  margin-bottom: 20px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 20px;
}

.stat-icon {
  width: 60px;
  height: 60px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 24px;
  flex-shrink: 0;
}

.stat-content {
  flex: 1;
  min-width: 0;
}

.stat-label {
  font-size: 14px;
  color: #909399;
  margin-bottom: 5px;
}

.stat-value {
  font-size: 24px;
  font-weight: bold;
  word-break: break-all;
}

.chart-card {
  min-height: 350px;
  margin-bottom: 20px;
}

.chart-container {
  height: 280px;
  width: 100%;
}

.profit-text {
  color: #67c23a;
  font-weight: bold;
}

.profit-text.negative {
  color: #f56c6c;
}

.value-text {
  color: #409eff;
  font-weight: bold;
}

.card-header {
  font-weight: bold;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

/* 响应式断点 */
@media (max-width: 1200px) {
  .overview-cards :deep(.el-col) {
    width: 50%;
  }
}

@media (max-width: 1024px) {
  .overview-cards :deep(.el-col) {
    width: 50%;
  }
  
  .chart-card {
    min-height: 300px;
  }
}

@media (max-width: 768px) {
  .stats-page {
    padding: 10px;
  }
  
  .page-header {
    flex-direction: column;
    align-items: stretch;
  }
  
  .page-header h1 {
    font-size: 20px;
    text-align: center;
  }
  
  .overview-cards :deep(.el-col) {
    width: 100%;
  }
  
  .stat-card {
    flex-direction: row;
    text-align: left;
  }
  
  .stat-icon {
    width: 50px;
    height: 50px;
    font-size: 20px;
  }
  
  .stat-value {
    font-size: 20px;
  }
  
  :deep(.el-row > .el-col) {
    width: 100% !important;
  }
  
  .chart-container {
    height: 220px;
  }
}

@media (max-width: 480px) {
  .stat-card {
    gap: 12px;
  }
  
  .stat-icon {
    width: 40px;
    height: 40px;
    font-size: 18px;
  }
  
  .stat-label {
    font-size: 12px;
  }
  
  .stat-value {
    font-size: 18px;
  }
  
  .chart-card {
    min-height: 250px;
  }
  
  .chart-container {
    height: 200px;
  }
}
</style>
