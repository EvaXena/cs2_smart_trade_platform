<template>
  <div class="orders-page">
    <div class="page-header">
      <h1>订单管理</h1>
    </div>

    <!-- 筛选 -->
    <el-card class="filter-card">
      <el-row :gutter="20">
        <el-col :span="4">
          <el-select v-model="filterStatus" placeholder="状态筛选" clearable>
            <el-option label="全部" value="" />
            <el-option label="待处理" value="pending" />
            <el-option label="处理中" value="processing" />
            <el-option label="已完成" value="completed" />
            <el-option label="已取消" value="cancelled" />
            <el-option label="失败" value="failed" />
          </el-select>
        </el-col>
        <el-col :span="6">
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
          />
        </el-col>
      </el-row>
    </el-card>

    <!-- 订单列表 -->
    <el-card class="orders-card">
      <el-table :data="orderList" v-loading="loading">
        <el-table-column prop="id" label="订单号" width="100" />
        <el-table-column prop="order_no" label="订单编号" width="180" />
        <el-table-column prop="item_name" label="商品名称" min-width="200" />
        <el-table-column prop="price" label="价格" width="120">
          <template #default="{ row }">
            ¥{{ row.price }}
          </template>
        </el-table-column>
        <el-table-column prop="quantity" label="数量" width="80" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)">
              {{ getStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="180" />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="handleView(row)">详情</el-button>
            <el-button 
              v-if="row.status === 'pending'"
              size="small" 
              type="danger"
              @click="handleCancel(row)"
            >
              取消
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pagination">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @size-change="handleSizeChange"
          @current-change="handlePageChange"
        />
      </div>
    </el-card>

    <!-- 订单详情对话框 -->
    <el-dialog v-model="detailDialogVisible" title="订单详情" width="600px">
      <el-descriptions :column="2" border v-if="currentOrder">
        <el-descriptions-item label="订单号">{{ currentOrder.id }}</el-descriptions-item>
        <el-descriptions-item label="订单编号">{{ currentOrder.order_no }}</el-descriptions-item>
        <el-descriptions-item label="商品名称" :span="2">{{ currentOrder.item_name }}</el-descriptions-item>
        <el-descriptions-item label="价格">¥{{ currentOrder.price }}</el-descriptions-item>
        <el-descriptions-item label="数量">{{ currentOrder.quantity }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="getStatusType(currentOrder.status)">
            {{ getStatusText(currentOrder.status) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ currentOrder.created_at }}</el-descriptions-item>
        <el-descriptions-item label="商品信息" :span="2">{{ currentOrder.item_data }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

const loading = ref(false)
const orderList = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const filterStatus = ref('')
const dateRange = ref([])
const detailDialogVisible = ref(false)
const currentOrder = ref<any>(null)

const getStatusType = (status: string) => {
  const types: Record<string, string> = {
    pending: 'warning',
    processing: 'primary',
    completed: 'success',
    cancelled: 'info',
    failed: 'danger'
  }
  return types[status] || 'info'
}

const getStatusText = (status: string) => {
  const texts: Record<string, string> = {
    pending: '待处理',
    processing: '处理中',
    completed: '已完成',
    cancelled: '已取消',
    failed: '失败'
  }
  return texts[status] || status
}

const fetchOrders = async () => {
  loading.value = true
  try {
    const token = localStorage.getItem('token')
    const response = await fetch(`/api/v1/orders?page=${currentPage.value}&limit=${pageSize.value}`, {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
    const data = await response.json()
    orderList.value = data.items || []
    total.value = data.total || 0
  } catch (error) {
    ElMessage.error('获取订单失败')
  } finally {
    loading.value = false
  }
}

const handleView = (row: any) => {
  currentOrder.value = row
  detailDialogVisible.value = true
}

const handleCancel = async (row: any) => {
  try {
    await ElMessageBox.confirm('确定要取消此订单吗？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    
    const token = localStorage.getItem('token')
    const response = await fetch(`/api/v1/orders/${row.id}/cancel`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
    if (response.ok) {
      ElMessage.success('取消成功')
      fetchOrders()
    } else {
      ElMessage.error('取消失败')
    }
  } catch (error) {
    // 用户取消
  }
}

const handleSizeChange = () => {
  fetchOrders()
}

const handlePageChange = () => {
  fetchOrders()
}

onMounted(() => {
  fetchOrders()
})
</script>

<style scoped>
.orders-page {
  padding: 20px;
}

.page-header {
  margin-bottom: 20px;
}

.page-header h1 {
  margin: 0;
  font-size: 24px;
}

.filter-card {
  margin-bottom: 20px;
}

.filter-card :deep(.el-row) {
  margin-left: -10px !important;
  margin-right: -10px !important;
}

.filter-card :deep(.el-col) {
  padding-left: 10px !important;
  padding-right: 10px !important;
  margin-bottom: 10px;
}

.orders-card {
  min-height: 400px;
}

/* 表格响应式 */
.orders-card :deep(.el-table) {
  overflow: hidden;
}

.pagination {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 10px;
}

/* 响应式断点 */
/* 平板端 */
@media (max-width: 1024px) {
  .filter-card :deep(.el-col) {
    width: 50% !important;
  }
  
  .orders-card :deep(.el-table) {
    min-width: 700px;
  }
}

/* 移动端 */
@media (max-width: 768px) {
  .orders-page {
    padding: 10px;
  }
  
  .page-header h1 {
    font-size: 20px;
  }
  
  .filter-card :deep(.el-col) {
    width: 100% !important;
  }
  
  .filter-card :deep(.el-date-picker) {
    width: 100% !important;
  }
  
  /* 表格卡片在小屏幕上使用横向滚动 */
  .orders-card {
    overflow-x: auto;
  }
  
  .orders-card :deep(.el-table) {
    min-width: 800px;
  }
  
  .pagination {
    justify-content: center;
  }
}

/* 小屏移动端 */
@media (max-width: 480px) {
  .page-header {
    margin-bottom: 10px;
  }
  
  /* 隐藏部分列 */
  .orders-card :deep(.el-table__body-wrapper) {
    overflow-x: auto;
  }
}
</style>
