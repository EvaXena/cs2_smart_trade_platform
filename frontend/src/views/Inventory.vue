<template>
  <div class="inventory-page">
    <div class="page-header">
      <h1>库存管理</h1>
      <div class="header-actions">
        <el-button type="primary" @click="handleSync">
          <el-icon><Refresh /></el-icon>
          同步库存
        </el-button>
      </div>
    </div>

    <!-- 筛选 -->
    <el-card class="filter-card">
      <el-row :gutter="20">
        <el-col :span="6">
          <el-select v-model="filterStatus" placeholder="状态筛选" clearable>
            <el-option label="全部" value="" />
            <el-option label="可用" value="available" />
            <el-option label="上架中" value="listing" />
            <el-option label="交易中" value="trading" />
            <el-option label="已售出" value="sold" />
          </el-select>
        </el-col>
        <el-col :span="6">
          <el-input
            v-model="searchKeyword"
            placeholder="搜索饰品名称"
            clearable
          />
        </el-col>
      </el-row>
    </el-card>

    <!-- 库存列表 -->
    <el-card class="inventory-card">
      <el-table :data="inventoryList" v-loading="loading">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="item_name" label="饰品名称" min-width="200" />
        <el-table-column prop="asset_id" label="Asset ID" width="150" />
        <el-table-column prop="cost_price" label="成本价" width="120">
          <template #default="{ row }">
            ¥{{ row.cost_price || 0 }}
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)">
              {{ getStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="float_value" label="Float" width="100" />
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="handleView(row)">详情</el-button>
            <el-button 
              size="small" 
              type="primary" 
              @click="handleList(row)"
              :disabled="row.status !== 'available'"
            >
              上架
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

    <!-- 上架对话框 -->
    <el-dialog v-model="listDialogVisible" title="上架饰品" width="500px">
      <el-form :model="listForm" label-width="80px">
        <el-form-item label="价格">
          <el-input-number v-model="listForm.price" :min="0" :precision="2" />
        </el-form-item>
        <el-form-item label="平台">
          <el-select v-model="listForm.platform">
            <el-option label="Steam 市场" value="steam" />
            <el-option label="BUFF" value="buff" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="listDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitList">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

const loading = ref(false)
const inventoryList = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const filterStatus = ref('')
const searchKeyword = ref('')
const listDialogVisible = ref(false)
const listForm = ref({
  inventoryId: 0,
  price: 0,
  platform: 'steam'
})

const getStatusType = (status: string) => {
  const types: Record<string, string> = {
    available: 'success',
    listing: 'warning',
    trading: 'primary',
    sold: 'info'
  }
  return types[status] || 'info'
}

const getStatusText = (status: string) => {
  const texts: Record<string, string> = {
    available: '可用',
    listing: '上架中',
    trading: '交易中',
    sold: '已售出'
  }
  return texts[status] || status
}

const fetchInventory = async () => {
  loading.value = true
  try {
    const token = localStorage.getItem('token')
    const response = await fetch(`/api/v1/inventory?page=${currentPage.value}&limit=${pageSize.value}`, {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
    const data = await response.json()
    inventoryList.value = data.items || []
    total.value = data.total || 0
  } catch (error) {
    ElMessage.error('获取库存失败')
  } finally {
    loading.value = false
  }
}

const handleSync = async () => {
  try {
    const token = localStorage.getItem('token')
    const response = await fetch('/api/v1/inventory/sync', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
    const data = await response.json()
    if (data.success) {
      ElMessage.success('同步成功')
      fetchInventory()
    } else {
      ElMessage.error(data.message || '同步失败')
    }
  } catch (error) {
    ElMessage.error('同步失败')
  }
}

const handleView = (row: any) => {
  console.log('查看详情', row)
}

const handleList = (row: any) => {
  listForm.value.inventoryId = row.id
  listForm.value.price = row.cost_price || 0
  listDialogVisible.value = true
}

const submitList = async () => {
  try {
    const token = localStorage.getItem('token')
    const response = await fetch('/api/v1/inventory/list', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        inventory_id: listForm.value.inventoryId,
        price: listForm.value.price,
        platform: listForm.value.platform
      })
    })
    if (response.ok) {
      ElMessage.success('上架成功')
      listDialogVisible.value = false
      fetchInventory()
    } else {
      ElMessage.error('上架失败')
    }
  } catch (error) {
    ElMessage.error('上架失败')
  }
}

const handleSizeChange = () => {
  fetchInventory()
}

const handlePageChange = () => {
  fetchInventory()
}

onMounted(() => {
  fetchInventory()
})
</script>

<style scoped>
.inventory-page {
  padding: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 10px;
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

.filter-card :deep(.el-select),
.filter-card :deep(.el-input) {
  width: 100%;
}

.inventory-card {
  min-height: 400px;
}

.inventory-card :deep(.el-table) {
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
  
  .inventory-card :deep(.el-table) {
    min-width: 600px;
  }
}

/* 移动端 */
@media (max-width: 768px) {
  .inventory-page {
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
  
  .header-actions {
    display: flex;
    justify-content: center;
  }
  
  .filter-card :deep(.el-col) {
    width: 100% !important;
  }
  
  .inventory-card {
    overflow-x: auto;
  }
  
  .inventory-card :deep(.el-table) {
    min-width: 700px;
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
}
</style>
