<template>
  <div v-if="visible" :class="['error-toast', type]">
    <el-icon v-if="showIcon" class="error-icon">
      <WarningFilled v-if="type === 'error'" />
      <InfoFilled v-else-if="type === 'info'" />
      <SuccessFilled v-else-if="type === 'success'" />
      <WarningFilled v-else />
    </el-icon>
    <div class="error-content">
      <div class="error-title">{{ title }}</div>
      <div v-if="message" class="error-message">{{ message }}</div>
      <div v-if="details" class="error-details">
        <pre>{{ details }}</pre>
      </div>
    </div>
    <el-icon v-if="closable" class="close-icon" @click="handleClose">
      <Close />
    </el-icon>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { WarningFilled, InfoFilled, SuccessFilled, Close } from '@element-plus/icons-vue'

interface Props {
  title?: string
  message?: string
  details?: string
  type?: 'error' | 'warning' | 'info' | 'success'
  duration?: number
  closable?: boolean
  showIcon?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  title: '操作失败',
  type: 'error',
  duration: 0,
  closable: true,
  showIcon: true,
})

const emit = defineEmits(['close', 'timeout'])

const visible = ref(true)

const handleClose = () => {
  visible.value = false
  emit('close')
}

// 自动关闭
if (props.duration > 0) {
  setTimeout(() => {
    handleClose()
    emit('timeout')
  }, props.duration)
}
</script>

<style scoped>
.error-toast {
  display: flex;
  align-items: flex-start;
  padding: 12px 16px;
  border-radius: 8px;
  margin: 8px 0;
  max-width: 400px;
  animation: slideIn 0.3s ease;
}

.error-toast.error {
  background: #fef0f0;
  border: 1px solid #fde2e2;
  color: #f56c6c;
}

.error-toast.warning {
  background: #fdf6ec;
  border: 1px solid #faecd8;
  color: #e6a23c;
}

.error-toast.info {
  background: #f4f4f5;
  border: 1px solid #ebe9f4;
  color: #909399;
}

.error-toast.success {
  background: #f0f9eb;
  border: 1px solid #e1f3d8;
  color: #67c23a;
}

.error-icon {
  font-size: 18px;
  margin-right: 12px;
  flex-shrink: 0;
}

.error-content {
  flex: 1;
  min-width: 0;
}

.error-title {
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 4px;
}

.error-message {
  font-size: 13px;
  opacity: 0.9;
}

.error-details {
  margin-top: 8px;
  padding: 8px;
  background: rgba(0, 0, 0, 0.05);
  border-radius: 4px;
  font-size: 12px;
  overflow-x: auto;
}

.error-details pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}

.close-icon {
  cursor: pointer;
  margin-left: 8px;
  opacity: 0.6;
  transition: opacity 0.2s;
}

.close-icon:hover {
  opacity: 1;
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
