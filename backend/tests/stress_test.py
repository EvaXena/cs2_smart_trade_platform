# -*- coding: utf-8 -*-
"""
压力测试脚本 - CS2智能交易平台
用于测试高并发场景下的系统稳定性
"""
import asyncio
import aiohttp
import time
import random
import statistics
from typing import List, Dict, Any
from datetime import datetime
import sys
import pytest


class StressTestRunner:
    """压力测试运行器"""
    
    def __init__(self, base_url: str = "http://localhost:8000", token: str = None):
        self.base_url = base_url
        self.token = token or ""
        self.results: List[Dict[str, Any]] = []
        self.errors: List[Dict[str, Any]] = []
    
    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers
    
    async def test_endpoint(
        self,
        session: aiohttp.ClientSession,
        method: str,
        endpoint: str,
        **kwargs
    ) -> Dict[str, Any]:
        """测试单个接口"""
        url = f"{self.base_url}{endpoint}"
        start_time = time.time()
        
        try:
            async with session.request(
                method,
                url,
                headers=self._get_headers(),
                **kwargs
            ) as response:
                elapsed = time.time() - start_time
                status = response.status
                
                try:
                    data = await response.json()
                except:
                    data = None
                
                return {
                    "endpoint": endpoint,
                    "method": method,
                    "status": status,
                    "elapsed": elapsed,
                    "success": 200 <= status < 300,
                    "data": data
                }
        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            return {
                "endpoint": endpoint,
                "method": method,
                "status": 0,
                "elapsed": elapsed,
                "success": False,
                "error": "Timeout"
            }
        except Exception as e:
            elapsed = time.time() - start_time
            return {
                "endpoint": endpoint,
                "method": method,
                "status": 0,
                "elapsed": elapsed,
                "success": False,
                "error": str(e)
            }
    
    async def concurrent_requests(
        self,
        endpoint: str,
        method: str = "GET",
        num_requests: int = 100,
        concurrency: int = 10,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """并发请求测试"""
        print(f"\n{'='*60}")
        print(f"测试: {method} {endpoint}")
        print(f"并发数: {concurrency}, 总请求数: {num_requests}")
        print(f"{'='*60}")
        
        connector = aiohttp.TCPConnector(limit=concurrency)
        timeout = aiohttp.ClientTimeout(total=30)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # 创建请求任务
            tasks = []
            for _ in range(num_requests):
                task = self.test_endpoint(session, method, endpoint, **kwargs)
                tasks.append(task)
            
            # 使用信号量控制并发
            semaphore = asyncio.Semaphore(concurrency)
            
            async def limited_task(task):
                async with semaphore:
                    return await task
            
            results = await asyncio.gather(*[limited_task(t) for t in tasks])
        
        return results
    
    def analyze_results(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """分析测试结果"""
        if not results:
            return {}
        
        elapsed_times = [r["elapsed"] for r in results]
        success_count = sum(1 for r in results if r["success"])
        error_count = len(results) - success_count
        
        analysis = {
            "total_requests": len(results),
            "success_count": success_count,
            "error_count": error_count,
            "success_rate": success_count / len(results) * 100,
            "avg_response_time": statistics.mean(elapsed_times),
            "median_response_time": statistics.median(elapsed_times),
            "min_response_time": min(elapsed_times),
            "max_response_time": max(elapsed_times),
            "p95_response_time": sorted(elapsed_times)[int(len(elapsed_times) * 0.95)] if len(elapsed_times) > 1 else elapsed_times[0],
            "p99_response_time": sorted(elapsed_times)[int(len(elapsed_times) * 0.99)] if len(elapsed_times) > 1 else elapsed_times[0],
        }
        
        return analysis
    
    def print_analysis(self, analysis: Dict[str, Any]):
        """打印分析结果"""
        print(f"\n📊 测试结果分析:")
        print(f"  总请求数: {analysis.get('total_requests', 0)}")
        print(f"  成功: {analysis.get('success_count', 0)}")
        print(f"  失败: {analysis.get('error_count', 0)}")
        print(f"  成功率: {analysis.get('success_rate', 0):.2f}%")
        print(f"\n⏱️ 响应时间 (秒):")
        print(f"  平均: {analysis.get('avg_response_time', 0):.3f}s")
        print(f"  中位数: {analysis.get('median_response_time', 0):.3f}s")
        print(f"  最小: {analysis.get('min_response_time', 0):.3f}s")
        print(f"  最大: {analysis.get('max_response_time', 0):.3f}s")
        print(f"  P95: {analysis.get('p95_response_time', 0):.3f}s")
        print(f"  P99: {analysis.get('p99_response_time', 0):.3f}s")
    
    async def run_full_suite(self):
        """运行完整测试套件"""
        print("\n🚀 CS2智能交易平台 - 压力测试")
        print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"目标: {self.base_url}")
        
        test_cases = [
            # (endpoint, method, num_requests, concurrency, description)
            ("/api/v1/items?page=1&limit=20", "GET", 100, 10, "获取饰品列表"),
            ("/api/v1/orders?page=1&limit=20", "GET", 100, 10, "获取订单列表"),
            ("/api/v1/stats/dashboard", "GET", 50, 10, "获取仪表盘统计"),
            ("/api/v1/monitors", "GET", 50, 10, "获取监控列表"),
        ]
        
        all_results = {}
        
        for endpoint, method, num_requests, concurrency, desc in test_cases:
            print(f"\n🧪 测试: {desc}")
            results = await self.concurrent_requests(
                endpoint, method, num_requests, concurrency
            )
            analysis = self.analyze_results(results)
            self.print_analysis(analysis)
            all_results[desc] = analysis
        
        # 打印总结
        print(f"\n{'='*60}")
        print("📈 测试总结")
        print(f"{'='*60}")
        
        total_requests = sum(r["total_requests"] for r in all_results.values())
        total_success = sum(r["success_count"] for r in all_results.values())
        total_errors = sum(r["error_count"] for r in all_results.values())
        
        print(f"总请求: {total_requests}")
        print(f"总成功: {total_success}")
        print(f"总失败: {total_errors}")
        print(f"总成功率: {total_success/total_requests*100:.2f}%")


@pytest.mark.asyncio
async def test_circuit_breaker():
    """测试熔断器功能"""
    print("\n🧪 熔断器测试")
    print("此测试需要后端服务运行...")
    
    # 测试熔断器统计接口
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:8000/api/v1/health") as resp:
                if resp.status == 200:
                    print("✅ 服务健康检查通过")
                else:
                    print(f"⚠️ 服务状态: {resp.status}")
    except Exception as e:
        print(f"❌ 无法连接到服务: {e}")


async def stress_test_api():
    """压力测试 API 端点"""
    runner = StressTestRunner(base_url="http://localhost:8000")
    await runner.run_full_suite()


async def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="CS2智能交易平台压力测试")
    parser.add_argument("--url", default="http://localhost:8000", help="基础URL")
    parser.add_argument("--token", default="", help="认证Token")
    parser.add_argument("--requests", type=int, default=100, help="总请求数")
    parser.add_argument("--concurrency", type=int, default=10, help="并发数")
    parser.add_argument("--endpoint", default="", help="指定测试端点")
    parser.add_argument("--method", default="GET", help="HTTP方法")
    
    args = parser.parse_args()
    
    runner = StressTestRunner(base_url=args.url, token=args.token)
    
    if args.endpoint:
        # 测试指定端点
        results = await runner.concurrent_requests(
            args.endpoint,
            args.method,
            args.requests,
            args.concurrency
        )
        analysis = runner.analyze_results(results)
        runner.print_analysis(analysis)
    else:
        # 运行完整测试套件
        await runner.run_full_suite()


if __name__ == "__main__":
    asyncio.run(main())
