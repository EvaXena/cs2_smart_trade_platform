# -*- coding: utf-8 -*-
"""
性能基准测试 - CS2智能交易平台
用于验证系统性能指标
"""
import asyncio
import time
import statistics
from typing import List, Dict, Any, Callable
from datetime import datetime
import pytest
import aiohttp

# 测试配置
API_BASE_URL = "http://localhost:8000"
CONCURRENT_USERS = [10, 50, 100, 200]
TEST_DURATION = 10  # 每个并发级别的测试持续时间（秒）


class BenchmarkResult:
    """基准测试结果"""
    
    def __init__(self, name: str):
        self.name = name
        self.times: List[float] = []
        self.errors: List[str] = []
        self.start_time = 0
        self.end_time = 0
    
    def add_result(self, elapsed: float, error: str = None):
        """添加测试结果"""
        self.times.append(elapsed)
        if error:
            self.errors.append(error)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        if not self.times:
            return {"error": "No data"}
        
        sorted_times = sorted(self.times)
        return {
            "name": self.name,
            "total_requests": len(self.times),
            "errors": len(self.errors),
            "success_rate": (len(self.times) - len(self.errors)) / len(self.times) * 100,
            "avg_time": statistics.mean(self.times),
            "median_time": statistics.median(self.times),
            "min_time": min(self.times),
            "max_time": max(sorted_times[-1]),
            "p95_time": sorted_times[int(len(sorted_times) * 0.95)],
            "p99_time": sorted_times[int(len(sorted_times) * 0.99)],
            "throughput": len(self.times) / (self.end_time - self.start_time) if self.end_time > self.start_time else 0,
        }


async def benchmark_endpoint(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    headers: Dict = None,
    json_data: Dict = None,
    num_requests: int = 100,
    concurrency: int = 10
) -> BenchmarkResult:
    """
    基准测试单个端点
    
    Args:
        session: aiohttp session
        method: HTTP 方法
        url: 请求 URL
        headers: 请求头
        json_data: JSON 请求体
        num_requests: 总请求数
        concurrency: 并发数
    
    Returns:
        BenchmarkResult
    """
    result = BenchmarkResult(f"{method} {url}")
    result.start_time = time.time()
    
    semaphore = asyncio.Semaphore(concurrency)
    
    async def make_request():
        async with semaphore:
            start = time.time()
            try:
                async with session.request(
                    method,
                    url,
                    headers=headers,
                    json=json_data,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    elapsed = time.time() - start
                    await response.read()
                    result.add_result(elapsed)
            except asyncio.TimeoutError:
                elapsed = time.time() - start
                result.add_result(elapsed, "Timeout")
            except Exception as e:
                elapsed = time.time() - start
                result.add_result(elapsed, str(e))
    
    # 创建所有任务
    tasks = [make_request() for _ in range(num_requests)]
    await asyncio.gather(*tasks)
    
    result.end_time = time.time()
    return result


async def run_benchmarks() -> List[Dict[str, Any]]:
    """运行所有基准测试"""
    print("\n" + "="*60)
    print("CS2智能交易平台 - 性能基准测试")
    print("="*60)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"目标: {API_BASE_URL}")
    print("="*60)
    
    all_results = []
    
    # 测试端点列表
    endpoints = [
        ("GET", "/api/v1/items?page=1&limit=20", None, None, "获取饰品列表"),
        ("GET", "/api/v1/orders?page=1&limit=20", None, None, "获取订单列表"),
        ("GET", "/api/v1/monitors", None, None, "获取监控列表"),
        ("GET", "/api/v1/stats/dashboard", None, None, "获取仪表盘统计"),
        ("GET", "/health", None, None, "健康检查"),
        ("GET", "/health/ready", None, None, "就绪检查"),
    ]
    
    headers = {"Content-Type": "application/json"}
    
    async with aiohttp.ClientSession() as session:
        # 先检查服务是否可用
        try:
            async with session.get(f"{API_BASE_URL}/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    print(f"⚠️ 服务不可用: {resp.status}")
                    return []
        except Exception as e:
            print(f"⚠️ 无法连接到服务: {e}")
            return []
        
        print("\n🚀 开始基准测试...")
        
        for method, url, _, _, desc in endpoints:
            print(f"\n📊 测试: {desc}")
            print("-" * 40)
            
            result = await benchmark_endpoint(
                session,
                method,
                f"{API_BASE_URL}{url}",
                headers=headers,
                num_requests=100,
                concurrency=10
            )
            
            stats = result.get_stats()
            all_results.append(stats)
            
            # 打印结果
            print(f"  总请求: {stats['total_requests']}")
            print(f"  错误: {stats['errors']}")
            print(f"  成功率: {stats['success_rate']:.2f}%")
            print(f"  平均响应: {stats['avg_time']*1000:.2f}ms")
            print(f"  P95响应: {stats['p95_time']*1000:.2f}ms")
            print(f"  吞吐量: {stats['throughput']:.2f} req/s")
    
    return all_results


def print_summary(results: List[Dict[str, Any]]):
    """打印测试摘要"""
    print("\n" + "="*60)
    print("📈 基准测试摘要")
    print("="*60)
    
    for r in results:
        print(f"\n{r['name']}")
        print(f"  成功率: {r['success_rate']:.2f}%")
        print(f"  平均: {r['avg_time']*1000:.2f}ms")
        print(f"  P95: {r['p95_time']*1000:.2f}ms")
        print(f"  吞吐量: {r['throughput']:.2f} req/s")
    
    print("\n" + "="*60)
    
    # 性能评级
    avg_throughput = statistics.mean([r['throughput'] for r in results if 'error' not in r])
    avg_latency = statistics.mean([r['avg_time']*1000 for r in results if 'error' not in r])
    
    if avg_throughput > 100 and avg_latency < 100:
        rating = "A - 优秀"
    elif avg_throughput > 50 and avg_latency < 200:
        rating = "B - 良好"
    elif avg_throughput > 20 and avg_latency < 500:
        rating = "C - 一般"
    else:
        rating = "D - 需优化"
    
    print(f"🎯 总体评级: {rating}")
    print(f"   平均吞吐量: {avg_throughput:.2f} req/s")
    print(f"   平均延迟: {avg_latency:.2f}ms")
    print("="*60)


@pytest.mark.asyncio
async def test_benchmark_items():
    """测试饰品列表性能"""
    results = await run_benchmarks()
    assert len(results) > 0, "没有测试结果"
    
    # 验证基本性能
    for r in results:
        if 'error' not in r:
            assert r['success_rate'] > 95, f"{r['name']} 成功率过低"
            assert r['avg_time'] < 1.0, f"{r['name']} 响应时间过长"


@pytest.mark.asyncio
async def test_concurrent_load():
    """测试并发负载"""
    print("\n" + "="*60)
    print("⚡ 并发负载测试")
    print("="*60)
    
    async with aiohttp.ClientSession() as session:
        for users in CONCURRENT_USERS:
            print(f"\n测试并发用户数: {users}")
            
            semaphore = asyncio.Semaphore(users)
            times = []
            
            async def make_request():
                async with semaphore:
                    start = time.time()
                    try:
                        async with session.get(
                            f"{API_BASE_URL}/api/v1/items?page=1&limit=20",
                            timeout=aiohttp.ClientTimeout(total=30)
                        ) as resp:
                            await resp.read()
                            times.append(time.time() - start)
                    except:
                        pass
            
            # 运行测试
            tasks = [make_request() for _ in range(users * 5)]
            await asyncio.gather(*tasks)
            
            if times:
                avg = statistics.mean(times)
                print(f"  平均响应时间: {avg*1000:.2f}ms")
                print(f"  成功请求: {len(times)}")


# ========== pytest 集成 ==========

@pytest.fixture(scope="module")
def benchmark_results():
    """基准测试结果 fixture"""
    results = asyncio.run(run_benchmarks())
    return results


def test_performance_check(benchmark_results):
    """性能检查测试"""
    assert len(benchmark_results) > 0
    
    for r in benchmark_results:
        if 'error' not in r:
            # 检查成功率
            assert r['success_rate'] >= 95, f"{r['name']} 成功率不达标"
            # 检查响应时间
            assert r['avg_time'] < 1.0, f"{r['name']} 平均响应时间超过1秒"


if __name__ == "__main__":
    results = asyncio.run(run_benchmarks())
    print_summary(results)
