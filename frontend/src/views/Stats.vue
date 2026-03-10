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
              <div class="stat-value">¥{{ overviewStats.total_volume.toFixed(2) }}</div>
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
            </div>
          </template>
          <div class="chart-placeholder">
            <el-empty description="图表加载中..." />
          </div>
        </el-card>
      </el-col>

      <!-- 利润趋势 -->
      <el-col :span="12">
        <el-card class="chart-card">
          <template #header>
            <div class="card-header">
              <span>利润趋势</span>
            </div>
          </template>
          <div class="chart-placeholder">
            <el-empty description="图表加载中..." />
          </div>
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
              <span class="profit-text">¥{{ profitStats.daily?.total_profit || 0 }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="本周利润">
              <span class="profit-text">¥{{ profitStats.weekly?.total_profit || 0 }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="本月利润">
              <span class="profit-text">¥{{ profitStats.monthly?.total_profit || 0 }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="累计利润">
              <span class="profit-text">¥{{ profitStats.all_time?.total_profit || 0 }}</span>
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
              <span class="value-text">¥{{ inventoryValue.total_value.toFixed(2) }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="Steam 库存">
              <span>¥{{ inventoryValue.by_platform?.steam?.toFixed(2) || 0 }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="BUFF 库存">
              <span>¥{{ inventoryValue.by_platform?.buff?.toFixed(2) || 0 }}</span>
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
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { User, Connection, ShoppingCart, Coin } from '@element-plus/icons-vue'

const loading = ref(false)
const dateRange = ref<[Date, Date] | null>(null)

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
const inventoryValue = ref({
  total_value: 0,
  by_platform: {},
  by_rarity: {},
  top_items: []
})

const recentTrades = ref([])

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
  }
}

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
  } catch (error) {
    console.error('获取利润统计失败', error)
  }
}

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
  } catch (error) {
    console.error('获取库存价值失败', error)
  }
}

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
  } catch (error) {
    console.error('获取最近交易失败', error)
  } finally {
    loading.value = false
  }
}

const handleDateChange = () => {
  // 重新加载数据
  fetchOverviewStats()
  fetchProfitStats()
}

onMounted(() => {
  fetchOverviewStats()
  fetchProfitStats()
  fetchInventoryValue()
  fetchRecentTrades()
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
  min-height: 300px;
  margin-bottom: 20px;
}

.chart-placeholder {
  height: 250px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.profit-text {
  color: #67c23a;
  font-weight: bold;
}

.value-text {
  color: #409eff;
  font-weight: bold;
}

.card-header {
  font-weight: bold;
}

/* 响应式断点 */
@media (max-width: 1200px) {
  .overview-cards :deep(.el-col) {
    width: 50%;
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
  
  /* 图表区域在移动端全宽 */
  :deep(.el-row > .el-col) {
    width: 100% !important;
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
  
  .chart-placeholder {
    height: 200px;
  }
}
</style>
