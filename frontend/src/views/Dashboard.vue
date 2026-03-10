<template>
  <div class="dashboard">
    <!-- 移动端菜单按钮 -->
    <div class="mobile-header" v-if="isMobile">
      <el-button :icon="Menu" @click="drawerVisible = true" circle />
      <span class="logo-text">CS2 Trade</span>
    </div>
    
    <el-container>
      <!-- 桌面端侧边栏 -->
      <el-aside v-if="!isMobile" width="200px">
        <div class="logo">CS2 Trade</div>
        <el-menu
          :default-active="activeMenu"
          router
          class="sidebar"
          :collapse="isCollapsed"
        >
          <el-menu-item index="/dashboard">
            <span>仪表盘</span>
          </el-menu-item>
          <el-menu-item index="/items">
            <span>饰品市场</span>
          </el-menu-item>
          <el-menu-item index="/orders">
            <span>订单管理</span>
          </el-menu-item>
          <el-menu-item index="/inventory">
            <span>我的库存</span>
          </el-menu-item>
          <el-menu-item index="/monitors">
            <span>价格监控</span>
          </el-menu-item>
          <el-menu-item index="/bots">
            <span>机器人</span>
          </el-menu-item>
          <el-menu-item index="/stats">
            <span>数据统计</span>
          </el-menu-item>
        </el-menu>
      </el-aside>
      
      <!-- 移动端抽屉 -->
      <el-drawer v-model="drawerVisible" direction="ltr" size="200px" v-if="isMobile">
        <div class="drawer-logo">CS2 Trade</div>
        <el-menu
          :default-active="activeMenu"
          router
          class="sidebar-drawer"
          @select="handleMenuSelect"
        >
          <el-menu-item index="/dashboard">
            <span>仪表盘</span>
          </el-menu-item>
          <el-menu-item index="/items">
            <span>饰品市场</span>
          </el-menu-item>
          <el-menu-item index="/orders">
            <span>订单管理</span>
          </el-menu-item>
          <el-menu-item index="/inventory">
            <span>我的库存</span>
          </el-menu-item>
          <el-menu-item index="/monitors">
            <span>价格监控</span>
          </el-menu-item>
          <el-menu-item index="/bots">
            <span>机器人</span>
          </el-menu-item>
          <el-menu-item index="/stats">
            <span>数据统计</span>
          </el-menu-item>
        </el-menu>
      </el-drawer>
      
      <el-container>
        <el-header>
          <div class="header-left">
            <el-button 
              v-if="!isMobile" 
              :icon="Fold" 
              @click="isCollapsed = !isCollapsed" 
              circle 
              size="small"
            />
          </div>
          <div class="header-right">
            <span class="username">{{ userStore.user?.username }}</span>
            <el-button @click="handleLogout" size="small">退出</el-button>
          </div>
        </el-header>
        
        <el-main>
          <router-view />
        </el-main>
      </el-container>
    </el-container>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore, useStatsStore } from '@/stores'
import { ElMessage } from 'element-plus'
import { Menu, Fold } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const statsStore = useStatsStore()

const activeMenu = computed(() => route.path)
const drawerVisible = ref(false)
const isCollapsed = ref(false)
const isMobile = ref(false)

const checkMobile = () => {
  isMobile.value = window.innerWidth < 768
}

const handleMenuSelect = () => {
  drawerVisible.value = false
}

onMounted(() => {
  checkMobile()
  window.addEventListener('resize', checkMobile)
  
  if (!userStore.isLoggedIn) {
    router.push('/login')
    return
  }
  statsStore.fetchDashboard()
})

onUnmounted(() => {
  window.removeEventListener('resize', checkMobile)
})

function handleLogout() {
  userStore.logout()
  ElMessage.success('已退出登录')
  router.push('/login')
}
</script>

<style scoped>
.dashboard {
  height: 100vh;
}

.el-container {
  height: 100%;
}

/* 移动端头部 */
.mobile-header {
  display: none;
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 50px;
  background: #304156;
  padding: 0 15px;
  align-items: center;
  gap: 15px;
  z-index: 1001;
}

.mobile-header .logo-text {
  color: #fff;
  font-size: 18px;
  font-weight: bold;
}

.el-aside {
  background-color: #304156;
  transition: width 0.3s;
}

.logo {
  height: 60px;
  line-height: 60px;
  text-align: center;
  color: #fff;
  font-size: 20px;
  font-weight: bold;
}

.drawer-logo {
  height: 60px;
  line-height: 60px;
  text-align: center;
  color: #fff;
  font-size: 20px;
  font-weight: bold;
  background-color: #304156;
  margin: -20px -20px 20px -20px;
}

.sidebar {
  border-right: none;
  background-color: #304156;
}

.sidebar-drawer {
  border-right: none;
  background-color: #304156;
}

.sidebar-drawer .el-menu-item {
  color: #bfcbd9;
}

.sidebar-drawer .el-menu-item:hover,
.sidebar-drawer .el-menu-item.is-active {
  background-color: #263445;
  color: #409eff;
}

.sidebar .el-menu-item {
  color: #bfcbd9;
}

.sidebar .el-menu-item:hover,
.sidebar .el-menu-item.is-active {
  background-color: #263445;
  color: #409eff;
}

/* 折叠状态 */
.sidebar:not(.el-menu--collapse) {
  width: 200px;
}

.el-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background-color: #fff;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
  padding: 0 20px;
}

.header-left {
  display: flex;
  align-items: center;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 15px;
}

.username {
  color: #606266;
}

.el-main {
  background-color: #f5f7fa;
  padding: 20px;
}

/* 响应式 - 平板端 */
@media (max-width: 1024px) {
  .el-aside {
    width: 180px !important;
  }
  
  .logo {
    font-size: 18px;
  }
  
  .sidebar:not(.el-menu--collapse) {
    width: 180px;
  }
}

/* 响应式 - 移动端 */
@media (max-width: 768px) {
  .mobile-header {
    display: flex;
  }
  
  .dashboard {
    padding-top: 50px;
    height: calc(100vh - 50px);
  }
  
  .el-aside {
    display: none;
  }
  
  .el-header {
    padding: 0 10px;
  }
  
  .el-main {
    padding: 10px;
  }
  
  .username {
    display: none;
  }
  
  .header-right {
    gap: 10px;
  }
}

/* 响应式 - 小屏移动端 */
@media (max-width: 480px) {
  .mobile-header .logo-text {
    font-size: 16px;
  }
  
  .header-left {
    display: none;
  }
}
</style>
