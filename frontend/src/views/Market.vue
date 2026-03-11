<template>
  <div class="market-page">
    <div class="page-header">
      <h1>饰品市场</h1>
      <div class="header-actions">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索饰品"
          class="search-input"
          clearable
          @keyup.enter="handleSearch"
        >
          <template #append>
            <el-button :icon="Search" @click="handleSearch" />
          </template>
        </el-input>
      </div>
    </div>

    <!-- 筛选 -->
    <el-card class="filter-card">
      <el-row :gutter="20">
        <el-col :span="4">
          <el-select v-model="filterCategory" placeholder="选择分类" clearable>
            <el-option label="全部" value="" />
            <el-option label="武器" value="weapon" />
            <el-option label="皮肤" value="skin" />
            <el-option label="刀具" value="knife" />
            <el-option label="手套" value="gloves" />
            <el-option label="胶囊" value="case" />
          </el-select>
        </el-col>
        <el-col :span="4">
          <el-select v-model="filterQuality" placeholder="品质" clearable>
            <el-option label="全部" value="" />
            <el-option label="普通" value="normal" />
            <el-option label="受限" value="restricted" />
            <el-option label="保密" value="classified" />
            <el-option label="军规" value="mil-spec" />
            <el-option label="隐秘" value="covert" />
          </el-select>
        </el-col>
        <el-col :span="4">
          <el-select v-model="sortBy" placeholder="排序">
            <el-option label="价格升序" value="price_asc" />
            <el-option label="价格降序" value="price_desc" />
            <el-option label="销量" value="sales" />
            <el-option label="最新上架" value="newest" />
          </el-select>
        </el-col>
        <el-col :span="4">
          <el-input-number
            v-model="priceMin"
            :min="0"
            placeholder="最低价"
            controls-position="right"
          />
        </el-col>
        <el-col :span="4">
          <el-input-number
            v-model="priceMax"
            :min="0"
            placeholder="最高价"
            controls-position="right"
          />
        </el-col>
      </el-row>
    </el-card>

    <!-- 市场列表 -->
    <el-row :gutter="20" class="items-grid">
      <el-col 
        v-for="item in itemList" 
        :key="item.id" 
        :xs="12" :sm="8" :md="6" :lg="4"
      >
        <el-card class="item-card" shadow="hover">
          <div class="item-image">
            <img :src="item.image || '/placeholder.png'" :alt="item.name" />
          </div>
          <div class="item-info">
            <h3 class="item-name">{{ item.name }}</h3>
            <p class="item-market-name">{{ item.market_hash_name }}</p>
            <div class="item-price">
              <span class="buff-price">BUFF: ¥{{ item.buff_price }}</span>
              <span class="steam-price">Steam: ¥{{ item.steam_price }}</span>
            </div>
            <div class="item-profit" v-if="(item.profit ?? 0) > 0">
              利润: ¥{{ item.profit }} ({{ item.profit_rate }}%)
            </div>
            <div class="item-actions">
              <el-button type="primary" size="small" @click="handleBuy(item)">
                购买
              </el-button>
              <el-button size="small" @click="handleAddMonitor(item)">
                监控
              </el-button>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

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
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import type { MarketItem } from '@/types'

const loading = ref(false)
const itemList = ref<MarketItem[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const searchKeyword = ref('')
const filterCategory = ref('')
const filterQuality = ref('')
const sortBy = ref('price_asc')
const priceMin = ref(0)
const priceMax = ref(0)

const fetchItems = async () => {
  loading.value = true
  try {
    const token = localStorage.getItem('token')
    const params = new URLSearchParams({
      page: currentPage.value.toString(),
      limit: pageSize.value.toString(),
      sort: sortBy.value
    })
    
    if (searchKeyword.value) params.append('keyword', searchKeyword.value)
    if (filterCategory.value) params.append('category', filterCategory.value)
    if (filterQuality.value) params.append('quality', filterQuality.value)
    if (priceMin.value) params.append('price_min', priceMin.value.toString())
    if (priceMax.value) params.append('price_max', priceMax.value.toString())
    
    const response = await fetch(`/api/v1/items?${params}`, {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
    const data = await response.json()
    itemList.value = data.items || []
    total.value = data.total || 0
  } catch (error) {
    ElMessage.error('获取市场数据失败')
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  currentPage.value = 1
  fetchItems()
}

const handleBuy = async (item: MarketItem) => {
  // 大额交易确认机制（阈值 ¥1000）
  if (item.buff_price >= 1000) {
    try {
      await ElMessageBox.confirm(
        `确认购买 ${item.name}，价格 ¥${item.buff_price}？`,
        '大额交易确认',
        {
          confirmButtonText: '确认购买',
          cancelButtonText: '取消',
          type: 'warning',
        }
      )
    } catch {
      // 用户取消
      ElMessage.info('已取消购买')
      return
    }
  }

  try {
    const token = localStorage.getItem('token')
    const response = await fetch('/api/v1/market/buy', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        item_id: item.id,
        price: item.buff_price,
        market_hash_name: item.market_hash_name,
      }),
    })

    const data = await response.json()
    
    if (response.ok) {
      ElMessage.success(`购买 ${item.name} 成功！`)
    } else {
      ElMessage.error(data.detail || '购买失败')
    }
  } catch (error) {
    ElMessage.error('购买请求失败')
  }
}

const handleAddMonitor = (item: MarketItem) => {
  ElMessage.info(`添加监控 ${item.name}`)
}

const handleSizeChange = () => {
  fetchItems()
}

const handlePageChange = () => {
  fetchItems()
}

onMounted(() => {
  fetchItems()
})
</script>

<style scoped>
.market-page {
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

.search-input {
  width: 300px;
  max-width: 100%;
}

/* 响应式筛选区域 */
.filter-card {
  margin-bottom: 20px;
}

.filter-card :deep(.el-row) {
  margin-left: 0 !important;
  margin-right: 0 !important;
}

.filter-card :deep(.el-col) {
  padding-left: 10px !important;
  padding-right: 10px !important;
  margin-bottom: 10px;
}

.filter-card :deep(.el-select),
.filter-card :deep(.el-input-number) {
  width: 100%;
}

/* 响应式网格 */
.items-grid {
  min-height: 400px;
}

.items-grid :deep(.el-col) {
  padding-left: 10px !important;
  padding-right: 10px !important;
  margin-bottom: 20px;
}

.item-card {
  margin-bottom: 0;
  cursor: pointer;
  transition: all 0.3s ease;
  height: 100%;
}

.item-card:hover {
  transform: translateY(-5px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.item-image {
  width: 100%;
  height: 150px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f7fa;
  border-radius: 4px;
}

.item-image img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

.item-info {
  padding: 10px 0;
}

.item-name {
  margin: 0 0 5px 0;
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-market-name {
  margin: 0 0 10px 0;
  font-size: 12px;
  color: #909399;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-price {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-bottom: 10px;
}

.buff-price {
  color: #f56c6c;
  font-weight: bold;
  font-size: 16px;
}

.steam-price {
  color: #909399;
  font-size: 12px;
}

.item-profit {
  color: #67c23a;
  font-size: 12px;
  margin-bottom: 10px;
}

.item-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.item-actions .el-button {
  flex: 1;
  min-width: 60px;
}

.pagination {
  margin-top: 20px;
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 10px;
}

/* 响应式断点样式 */
/* 平板端 */
@media (max-width: 1024px) {
  .items-grid :deep(.el-col) {
    width: 33.33% !important;
  }
  
  .filter-card :deep(.el-col) {
    width: 33.33% !important;
  }
}

/* 移动端 */
@media (max-width: 768px) {
  .market-page {
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
  
  .search-input {
    width: 100%;
  }
  
  .filter-card :deep(.el-col) {
    width: 100% !important;
  }
  
  .item-image {
    height: 120px;
  }
  
  .item-name {
    font-size: 13px;
  }
  
  .buff-price {
    font-size: 14px;
  }
  
  .pagination :deep(.el-pagination) {
    white-space: normal;
  }
}

/* 小屏移动端 */
@media (max-width: 480px) {
  .page-header {
    margin-bottom: 10px;
  }
  
  .items-grid :deep(.el-col) {
    width: 100% !important;
  }
  
  .item-card {
    display: flex;
    flex-direction: row;
  }
  
  .item-card :deep(.el-card__body) {
    display: flex;
    flex-direction: row;
    width: 100%;
  }
  
  .item-image {
    width: 80px;
    height: 80px;
    flex-shrink: 0;
  }
  
  .item-info {
    flex: 1;
    padding: 0 0 0 10px;
    display: flex;
    flex-direction: column;
    justify-content: center;
  }
  
  .item-name,
  .item-market-name {
    white-space: normal;
    text-overflow: initial;
  }
  
  .item-actions {
    flex-direction: column;
    gap: 5px;
  }
  
  .item-actions .el-button {
    width: 100%;
  }
}
</style>
