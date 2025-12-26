import winreg
import os
import json
import shutil
import subprocess
import filecmp
from pathlib import Path

# 全局配置
CONFIG_PATH = "./config/config.json"
BACKUP_ROOT = "./saves"

def get_special_folder_from_registry(folder_name: str) -> str:
    # 从Windows注册表获取特殊文件夹路径（支持重定向的Documents/AppData等）
    # folder_name: 注册表键名，支持 "Personal"(Documents)、"AppData"、"Local AppData" 等
    # return: 真实的文件夹路径
    try:
        # 打开注册表路径（Shell Folders 存储用户自定义的文件夹路径）
        reg_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        reg_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path)
        
        # 查询指定键值
        path_value, _ = winreg.QueryValueEx(reg_key, folder_name)
        
        # 关闭注册表键（避免资源泄漏）
        winreg.CloseKey(reg_key)
        
        # 解析路径中的环境变量（比如 %USERPROFILE% 会被替换为真实路径）
        resolved_path = os.path.expandvars(path_value)
        
        return resolved_path
    except FileNotFoundError:
        raise ValueError(f"注册表路径或键名不存在: {folder_name}")
    except Exception as e:
        raise RuntimeError(f"从注册表获取路径失败: {str(e)}")

# 封装常用的特殊文件夹获取函数
def get_documents_path() -> str:
    # 获取我的文档路径（Personal对应Documents）
    return get_special_folder_from_registry("Personal")

def get_appdata_roaming_path() -> str:
    # 获取AppData\Roaming路径
    return get_special_folder_from_registry("AppData")

def get_local_appdata_path() -> str:
    # 获取AppData\Local路径
    return get_special_folder_from_registry("Local AppData")

def resolve_game_save_path(placeholder_path: str) -> tuple[str, str]:
    # 解析配置文件中的占位符路径，返回(真实路径, 存档文件夹名)
    # 示例: %Documents%/Euro Truck Simulator 2 -> (真实路径, Euro Truck Simulator 2)
    # 替换占位符为注册表获取的真实路径
    path = placeholder_path.replace(
        "%Documents%", get_documents_path()
    ).replace(
        "%AppData%", get_appdata_roaming_path()
    ).replace(
        "%AppDataLocal%", get_local_appdata_path()
    )
    
    # 标准化路径格式
    real_path = os.path.normpath(path)
    # 提取最后一级文件夹名
    folder_name = os.path.basename(real_path)
    
    return real_path, folder_name

def run_git_command(cmd: list) -> tuple[bool, str]:
    # 执行Git命令，返回(是否成功, 输出/错误信息)
    try:
        result = subprocess.run(
            cmd,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            encoding="utf-8"
        )
        if result.returncode == 0:
            return True, result.stdout
        else:
            return False, result.stderr
    except Exception as e:
        return False, str(e)

def check_git_status() -> tuple[bool, str]:
    # 检查Git工作区是否干净，返回(是否干净, 提示信息)
    # 先拉取最新代码，检测远程变更
    success, output = run_git_command(["git", "pull"])
    if not success:
        return False, f"Git pull失败: {output}"
    
    # 检查本地修改
    success, output = run_git_command(["git", "status", "--porcelain"])
    if not success:
        return False, f"检查Git状态失败: {output}"
    
    if output.strip() != "":
        return False, f"Git工作区有未提交变更:\n{output}"
    
    return True, "Git工作区干净"

def compare_folders(src: str, dst: str) -> bool:
    # 递归比较两个文件夹内容是否一致，返回是否一致
    try:
        cmp = filecmp.dircmp(src, dst)
        # 检查是否有不同文件、只在一侧存在的文件
        if cmp.diff_files or cmp.left_only or cmp.right_only or cmp.funny_files:
            return False
        # 递归检查子文件夹
        for subdir in cmp.common_dirs:
            if not compare_folders(os.path.join(src, subdir), os.path.join(dst, subdir)):
                return False
        return True
    except FileNotFoundError:
        return False
    except Exception as e:
        print(f"比较文件夹失败: {e}")
        return False

def sync_game_saves():
    # 同步存档（make sync）：将游戏存档备份到Git工程，并检测冲突
    print("=== 开始同步游戏存档 ===")
    
    # 1. 检查Git状态
    git_clean, git_msg = check_git_status()
    if not git_clean:
        print(f"错误: {git_msg}")
        print("请先提交/解决Git冲突后再执行同步")
        return
    
    # 2. 读取配置文件
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        print(f"读取配置文件失败：{e}")
        return
    
    # 3. 遍历游戏列表备份
    for game in config.get("saves", []):
        game_name = game.get("Name")
        save_dir_placeholder = game.get("SaveDir")
        
        if not game_name or not save_dir_placeholder:
            print(f"跳过：游戏配置不完整")
            continue
        
        # 解析真实存档路径和文件夹名
        try:
            real_save_dir, folder_name = resolve_game_save_path(save_dir_placeholder)
        except Exception as e:
            print(f"[{game_name}] 解析路径失败：{e}")
            continue
        
        # 检查源存档目录是否存在
        if not os.path.exists(real_save_dir):
            print(f"[{game_name}] 存档目录不存在：{real_save_dir}")
            continue
        
        # 构建备份目标路径：saves/游戏名/存档文件夹名
        backup_target = os.path.join(BACKUP_ROOT, game_name, folder_name)
        Path(backup_target).mkdir(parents=True, exist_ok=True)
        
        # 检查是否已有备份且内容不一致
        conflict = False
        if os.path.exists(backup_target):
            if not compare_folders(real_save_dir, backup_target):
                conflict = True
                print(f"[{game_name}] 检测到存档内容不一致（冲突）！")
                print(f"  源路径: {real_save_dir}")
                print(f"  备份路径: {backup_target}")
                user_choice = input("是否覆盖备份？(y/N): ").strip().lower()
                if user_choice != "y":
                    print(f"[{game_name}] 取消备份")
                    continue
        
        # 执行备份（覆盖或首次备份）
        try:
            # 先清空目标目录（避免残留文件）
            for item in os.listdir(backup_target):
                item_path = os.path.join(backup_target, item)
                if os.path.isfile(item_path):
                    os.remove(item_path)
                else:
                    shutil.rmtree(item_path)
            
            # 递归复制存档
            shutil.copytree(real_save_dir, backup_target, dirs_exist_ok=True)
            print(f"[{game_name}] 存档备份成功：{backup_target}")
            
            # Git提交变更
            if conflict or not os.path.exists(os.path.join(backup_target, ".git")):
                run_git_command(["git", "add", backup_target])
                success, output = run_git_command([
                    "git", "commit", "-m", f"Sync {game_name} saves - {folder_name}"
                ])
                if success:
                    print(f"[{game_name}] Git提交成功")
                    # 推送变更
                    success, output = run_git_command(["git", "push"])
                    if success:
                        print(f"[{game_name}] Git推送成功")
                    else:
                        print(f"[{game_name}] Git推送失败：{output}")
                else:
                    print(f"[{game_name}] Git提交失败：{output}")
        
        except Exception as e:
            print(f"[{game_name}] 备份失败：{e}")
    
    print("=== 同步完成 ===")

def apply_game_saves():
    # 应用存档（make apply）：将Git工程中的存档恢复到游戏目录
    print("=== 开始应用游戏存档 ===")
    
    # 1. 检查Git状态
    git_clean, git_msg = check_git_status()
    if not git_clean:
        print(f"错误: {git_msg}")
        print("请先提交/解决Git冲突后再执行应用")
        return
    
    # 2. 读取配置文件
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        print(f"读取配置文件失败：{e}")
        return
    
    # 3. 遍历游戏列表恢复存档
    for game in config.get("saves", []):
        game_name = game.get("Name")
        save_dir_placeholder = game.get("SaveDir")
        
        if not game_name or not save_dir_placeholder:
            print(f"跳过：游戏配置不完整")
            continue
        
        # 解析真实存档路径和文件夹名
        try:
            real_save_dir, folder_name = resolve_game_save_path(save_dir_placeholder)
        except Exception as e:
            print(f"[{game_name}] 解析路径失败：{e}")
            continue
        
        # 构建备份源路径：saves/游戏名/存档文件夹名
        backup_source = os.path.join(BACKUP_ROOT, game_name, folder_name)
        
        # 检查备份目录是否存在
        if not os.path.exists(backup_source):
            print(f"[{game_name}] 备份存档不存在：{backup_source}")
            continue
        
        # 检查目标目录是否存在且内容不一致
        conflict = False
        if os.path.exists(real_save_dir):
            if not compare_folders(backup_source, real_save_dir):
                conflict = True
                print(f"[{game_name}] 检测到目标存档内容不一致（冲突）！")
                print(f"  目标路径: {real_save_dir}")
                print(f"  备份路径: {backup_source}")
                user_choice = input("是否覆盖目标存档？(y/N): ").strip().lower()
                if user_choice != "y":
                    print(f"[{game_name}] 取消应用")
                    continue
        
        # 执行恢复
        try:
            # 先清空目标目录（避免残留文件）
            if os.path.exists(real_save_dir):
                for item in os.listdir(real_save_dir):
                    item_path = os.path.join(real_save_dir, item)
                    if os.path.isfile(item_path):
                        os.remove(item_path)
                    else:
                        shutil.rmtree(item_path)
            
            # 递归复制存档
            shutil.copytree(backup_source, real_save_dir, dirs_exist_ok=True)
            print(f"[{game_name}] 存档应用成功：{real_save_dir}")
        
        except Exception as e:
            print(f"[{game_name}] 应用失败：{e}")
    
    print("=== 应用完成 ===")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法:")
        print("  python scripts/save.py sync   # 同步存档到Git工程")
        print("  python scripts/save.py apply  # 应用Git工程中的存档")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    if command == "sync":
        sync_game_saves()
    elif command == "apply":
        apply_game_saves()
    else:
        print(f"未知命令: {command}")
        sys.exit(1)
