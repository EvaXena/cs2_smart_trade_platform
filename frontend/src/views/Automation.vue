<template>
  <div class="automation-page">
    <div class="page-header">
      <h1>自动化交易</h1>
      <div class="header-actions">
        <el-button type="primary" @click="handleCreateRule">
          <el-icon><Plus /></el-icon>
          创建规则
        </el-button>
      </div>
    </div>

    <!-- 自动化规则列表 -->
    <el-card class="rules-card">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="自动购买" name="buy">
          <el-table :data="buyRules" v-loading="loading">
            <el-table-column prop="id" label="ID" width="80" />
            <el-table-column prop="name" label="规则名称" min-width="150" />
            <el-table-column prop="item_pattern" label="饰品匹配" min-width="200" />
            <el-table-column prop="condition" label="触发条件" width="150">
              <template #default="{ row }">
                {{ getConditionText(row.condition) }}
              </template>
            </el-table-column>
            <el-table-column prop="max_price" label="最高价格" width="120">
              <template #default="{ row }">
                ¥{{ row.max_price }}
              </template>
            </el-table-column>
            <el-table-column prop="enabled" label="状态" width="100">
              <template #default="{ row }">
                <el-switch
                  v-model="row.enabled"
                  @change="handleToggleRule(row)"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="200" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="handleEditRule(row)">编辑</el-button>
                <el-button size="small" type="danger" @click="handleDeleteRule(row)">
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="自动出售" name="sell">
          <el-table :data="sellRules" v-loading="loading">
            <el-table-column prop="id" label="ID" width="80" />
            <el-table-column prop="name" label="规则名称" min-width="150" />
            <el-table-column prop="item_pattern" label="饰品匹配" min-width="200" />
            <el-table-column prop="condition" label="触发条件" width="150">
              <template #default="{ row }">
                {{ getConditionText(row.condition) }}
              </template>
            </el-table-column>
            <el-table-column prop="min_profit" label="最低利润" width="120">
              <template #default="{ row }">
                ¥{{ row.min_profit }}
              </template>
            </el-table-column>
            <el-table-column prop="enabled" label="状态" width="100">
              <template #default="{ row }">
                <el-switch
                  v-model="row.enabled"
                  @change="handleToggleRule(row)"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="200" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="handleEditRule(row)">编辑</el-button>
                <el-button size="small" type="danger" @click="handleDeleteRule(row)">
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="套利规则" name="arbitrage">
          <el-table :data="arbitrageRules" v-loading="loading">
            <el-table-column prop="id" label="ID" width="80" />
            <el-table-column prop="name" label="规则名称" min-width="150" />
            <el-table-column prop="item_pattern" label="饰品匹配" min-width="200" />
            <el-table-column prop="min_profit_rate" label="最小利润率" width="120">
              <template #default="{ row }">
                {{ row.min_profit_rate }}%
              </template>
            </el-table-column>
            <el-table-column prop="max_amount" label="最大金额" width="120">
              <template #default="{ row }">
                ¥{{ row.max_amount }}
              </template>
            </el-table-column>
            <el-table-column prop="enabled" label="状态" width="100">
              <template #default="{ row }">
                <el-switch
                  v-model="row.enabled"
                  @change="handleToggleRule(row)"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="200" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="handleEditRule(row)">编辑</el-button>
                <el-button size="small" type="danger" @click="handleDeleteRule(row)">
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 创建/编辑规则对话框 -->
    <el-dialog 
      v-model="ruleDialogVisible" 
      :title="isEdit ? '编辑规则' : '创建规则'" 
      width="600px"
    >
      <el-form :model="ruleForm" label-width="100px">
        <el-form-item label="规则名称">
          <el-input v-model="ruleForm.name" placeholder="请输入规则名称" />
        </el-form-item>
        <el-form-item label="规则类型">
          <el-select v-model="ruleForm.type">
            <el-option label="自动购买" value="buy" />
            <el-option label="自动出售" value="sell" />
            <el-option label="套利" value="arbitrage" />
          </el-select>
        </el-form-item>
        <el-form-item label="饰品匹配">
          <el-input v-model="ruleForm.item_pattern" placeholder="输入饰品名称或使用 * 通配符" />
        </el-form-item>
        <el-form-item label="触发条件">
          <el-select v-model="ruleForm.condition">
            <el-option label="价格低于" value="price_below" />
            <el-option label="价格高于" value="price_above" />
            <el-option label="价格下跌" value="price_drop" />
            <el-option label="价格上涨" value="price_rise" />
            <el-option label="套利机会" value="arbitrage" />
          </el-select>
        </el-form-item>
        <el-form-item label="阈值">
          <el-input-number v-model="ruleForm.threshold" :min="0" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="ruleForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="ruleDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitRule">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'

const loading = ref(false)
const activeTab = ref('buy')
const buyRules = ref([])
const sellRules = ref([])
const arbitrageRules = ref([])
const ruleDialogVisible = ref(false)
const isEdit = ref(false)
const ruleForm = ref({
  id: 0,
  name: '',
  type: 'buy',
  item_pattern: '',
  condition: 'price_below',
  threshold: 0,
  enabled: true
})

const getConditionText = (condition: string) => {
  const texts: Record<string, string> = {
    price_below: '价格低于',
    price_above: '价格高于',
    price_drop: '价格下跌',
    price_rise: '价格上涨',
    arbitrage: '套利机会'
  }
  return texts[condition] || condition
}

const fetchRules = async () => {
  loading.value = true
  try {
    const token = localStorage.getItem('token')
    const response = await fetch('/api/v1/monitors', {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
    const data = await response.json()
    const rules = data.items || []
    
    // 按类型分组
    buyRules.value = rules.filter((r: any) => r.action === 'auto_buy')
    sellRules.value = rules.filter((r: any) => r.action === 'auto_sell')
    arbitrageRules.value = rules.filter((r: any) => r.action === 'arbitrage')
  } catch (error) {
    ElMessage.error('获取规则失败')
  } finally {
    loading.value = false
  }
}

const handleCreateRule = () => {
  isEdit.value = false
  ruleForm.value = {
    id: 0,
    name: '',
    type: 'buy',
    item_pattern: '',
    condition: 'price_below',
    threshold: 0,
    enabled: true
  }
  ruleDialogVisible.value = true
}

const handleEditRule = (row: any) => {
  isEdit.value = true
  ruleForm.value = { ...row }
  ruleDialogVisible.value = true
}

const handleDeleteRule = async (row: any) => {
  try {
    await ElMessageBox.confirm('确定要删除此规则吗？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    
    const token = localStorage.getItem('token')
    const response = await fetch(`/api/v1/monitors/${row.id}`, {
      method: 'DELETE',
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
    if (response.ok) {
      ElMessage.success('删除成功')
      fetchRules()
    } else {
      ElMessage.error('删除失败')
    }
  } catch (error) {
    // 用户取消
  }
}

const handleToggleRule = async (row: any) => {
  try {
    const token = localStorage.getItem('token')
    const response = await fetch(`/api/v1/monitors/${row.id}`, {
      method: 'PUT',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ enabled: row.enabled })
    })
    if (response.ok) {
      ElMessage.success(row.enabled ? '已启用' : '已禁用')
    } else {
      ElMessage.error('操作失败')
    }
  } catch (error) {
    ElMessage.error('操作失败')
  }
}

const submitRule = async () => {
  try {
    const token = localStorage.getItem('token')
    const actionMap: Record<string, string> = {
      buy: 'auto_buy',
      sell: 'auto_sell',
      arbitrage: 'arbitrage'
    }
    
    const data = {
      name: ruleForm.value.name,
      item_pattern: ruleForm.value.item_pattern,
      condition_type: ruleForm.value.condition,
      threshold: ruleForm.value.threshold,
      action: actionMap[ruleForm.value.type],
      enabled: ruleForm.value.enabled
    }
    
    let response
    if (isEdit.value) {
      response = await fetch(`/api/v1/monitors/${ruleForm.value.id}`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(data)
      })
    } else {
      response = await fetch('/api/v1/monitors', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(data)
      })
    }
    
    if (response.ok) {
      ElMessage.success(isEdit.value ? '更新成功' : '创建成功')
      ruleDialogVisible.value = false
      fetchRules()
    } else {
      ElMessage.error(isEdit.value ? '更新失败' : '创建失败')
    }
  } catch (error) {
    ElMessage.error('操作失败')
  }
}

onMounted(() => {
  fetchRules()
})
</script>

<style scoped>
.automation-page {
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

.rules-card {
  min-height: 400px;
}

.rules-card :deep(.el-table) {
  overflow: hidden;
}

/* 响应式断点 */
@media (max-width: 768px) {
  .automation-page {
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
  
  .rules-card {
    overflow-x: auto;
  }
  
  .rules-card :deep(.el-table) {
    min-width: 700px;
  }
}

@media (max-width: 480px) {
  .page-header {
    margin-bottom: 10px;
  }
}
</style>
