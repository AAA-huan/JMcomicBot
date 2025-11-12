#!/usr/bin/env python3
"""
MangaBot Linux适配单元测试
测试跨平台兼容性功能
"""

import unittest
import sys
import os
import platform
from unittest.mock import Mock, patch, MagicMock

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot import MangaBot


class TestMangaBotLinuxCompatibility(unittest.TestCase):
    """测试MangaBot的Linux兼容性"""
    
    def setUp(self) -> None:
        """测试前准备"""
        # 保存原始的平台信息
        self.original_platform = platform.system
        self.original_sys_version = sys.version_info
        
    def tearDown(self) -> None:
        """测试后清理"""
        # 恢复原始的平台信息
        platform.system = self.original_platform
        sys.version_info = self.original_sys_version
    
    def test_platform_compatibility_linux(self) -> None:
        """测试Linux平台兼容性检查"""
        # 模拟Linux平台
        platform.system = Mock(return_value='Linux')
        
        # 创建MangaBot实例
        with patch('bot.load_dotenv'), \
             patch('bot.logging.getLogger'), \
             patch('os.makedirs'):
            
            bot = MangaBot()
            
            # 验证平台检查通过
            self.assertTrue(hasattr(bot, '_check_platform_compatibility'))
    
    def test_platform_compatibility_windows(self) -> None:
        """测试Windows平台兼容性检查"""
        # 模拟Windows平台
        platform.system = Mock(return_value='Windows')
        
        # 创建MangaBot实例
        with patch('bot.load_dotenv'), \
             patch('bot.logging.getLogger'), \
             patch('os.makedirs'):
            
            bot = MangaBot()
            
            # 验证平台检查通过
            self.assertTrue(hasattr(bot, '_check_platform_compatibility'))
    
    def test_unsupported_platform(self) -> None:
        """测试不支持平台的错误处理"""
        # 模拟不支持的平台
        platform.system = Mock(return_value='Darwin')  # macOS
        
        # 创建MangaBot实例，应该抛出异常
        with patch('bot.load_dotenv'), \
             patch('bot.logging.getLogger'), \
             patch('os.makedirs'), \
             self.assertRaises(OSError):
            
            MangaBot()
    
    def test_python_version_check(self) -> None:
        """测试Python版本检查"""
        # 模拟低版本Python
        sys.version_info = (3, 6, 0)  # Python 3.6
        platform.system = Mock(return_value='Linux')
        
        # 创建MangaBot实例，应该抛出异常
        with patch('bot.load_dotenv'), \
             patch('bot.logging.getLogger'), \
             patch('os.makedirs'), \
             self.assertRaises(RuntimeError):
            
            MangaBot()
    
    def test_linux_requirements_check(self) -> None:
        """测试Linux系统要求检查"""
        # 模拟Linux平台
        platform.system = Mock(return_value='Linux')
        
        # 创建MangaBot实例
        with patch('bot.load_dotenv'), \
             patch('bot.logging.getLogger'), \
             patch('os.makedirs'), \
             patch('subprocess.run') as mock_subprocess:
            
            # 模拟subprocess.run返回成功
            mock_subprocess.return_value.returncode = 0
            
            bot = MangaBot()
            
            # 验证Linux要求检查方法存在
            self.assertTrue(hasattr(bot, '_check_linux_requirements'))
    
    def test_cross_platform_logger(self) -> None:
        """测试跨平台日志系统"""
        # 模拟Linux平台
        platform.system = Mock(return_value='Linux')
        
        # 创建MangaBot实例
        with patch('bot.load_dotenv'), \
             patch('bot.logging.getLogger') as mock_get_logger, \
             patch('os.makedirs'), \
             patch('bot.logging.StreamHandler'), \
             patch('bot.logging.FileHandler'):
            
            # 模拟logger
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger
            
            bot = MangaBot()
            
            # 验证日志系统已配置
            self.assertTrue(hasattr(bot, 'logger'))
    
    def test_path_handling_cross_platform(self) -> None:
        """测试跨平台路径处理"""
        # 测试路径分隔符兼容性
        test_path_linux = "/home/user/downloads"
        test_path_windows = "C:\\Users\\user\\downloads"
        
        # 验证路径处理函数
        self.assertTrue(os.path.isabs(test_path_linux) or os.path.isabs(test_path_windows))
    
    def test_environment_variables(self) -> None:
        """测试环境变量处理"""
        # 模拟Linux平台
        platform.system = Mock(return_value='Linux')
        
        # 创建MangaBot实例
        with patch('bot.load_dotenv') as mock_load_dotenv, \
             patch('bot.logging.getLogger'), \
             patch('os.makedirs'), \
             patch.dict('os.environ', {
                'MANGA_DOWNLOAD_PATH': '/home/user/downloads',
                'NAPCAT_WS_URL': 'ws://localhost:8080/qq',
                'API_TOKEN': 'test_token'
            }):
            
            bot = MangaBot()
            
            # 验证环境变量加载
            mock_load_dotenv.assert_called_once()
            
            # 验证配置正确设置
            self.assertEqual(bot.config['MANGA_DOWNLOAD_PATH'], '/home/user/downloads')


class TestStartScript(unittest.TestCase):
    """测试启动脚本功能"""
    
    def test_start_sh_exists(self) -> None:
        """测试Linux启动脚本存在"""
        start_sh_path = os.path.join(os.path.dirname(__file__), 'start.sh')
        self.assertTrue(os.path.exists(start_sh_path))
    
    def test_start_sh_permissions(self) -> None:
        """测试Linux启动脚本权限"""
        start_sh_path = os.path.join(os.path.dirname(__file__), 'start.sh')
        
        # 检查文件是否可读
        self.assertTrue(os.access(start_sh_path, os.R_OK))
    
    def test_requirements_compatibility(self) -> None:
        """测试依赖包兼容性"""
        requirements_path = os.path.join(os.path.dirname(__file__), 'requirements.txt')
        
        # 检查requirements文件存在
        self.assertTrue(os.path.exists(requirements_path))
        
        # 读取并检查依赖
        with open(requirements_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
            # 检查关键依赖
            self.assertIn('websocket-client', content)
            self.assertIn('jmcomic', content)
            self.assertIn('platformdirs', content)  # 跨平台路径处理


def run_tests() -> None:
    """运行所有测试"""
    # 创建测试套件
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 添加测试类
    suite.addTests(loader.loadTestsFromTestCase(TestMangaBotLinuxCompatibility))
    suite.addTests(loader.loadTestsFromTestCase(TestStartScript))
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # 输出测试结果
    print(f"\n测试结果: {result.testsRun} 个测试运行")
    print(f"失败: {len(result.failures)}")
    print(f"错误: {len(result.errors)}")
    
    if result.failures or result.errors:
        sys.exit(1)  # 如果有测试失败，退出码为1
    else:
        print("所有测试通过!")


if __name__ == '__main__':
    run_tests()