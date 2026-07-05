# ken-water-meter

上海肯特渗漏控制管理平台 - 水表数据获取工具

## 功能

- 自动登录上海肯特水表数据管理平台
- 提取指定监测点的流量数据
- 计算每日供水量（基于凌晨2-4点平均流量）
- 生成 CSV 格式报表

## 环境要求

- Python 3.7+
- 本项目仅使用 Python 标准库，无需额外安装依赖

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/dengdef/ken-water-meter.git
cd ken-water-meter
```

### 2. 创建虚拟环境（推荐）

**Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**Windows (Command Prompt):**
```cmd
python -m venv venv
venv\Scripts\activate.bat
```

**Linux/Mac:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. 运行程序

```bash
python ken.py
```

## 输出

运行后会生成 `data.csv` 文件，包含以下字段：

| 字段 | 说明 |
|------|------|
| 时间 | 日期（YYYY-MM-DD） |
| 地址 | 监测点地址 |
| 瞬时流量 | 凌晨2-4点平均瞬时流量 |
| 日供水量 | 当日供水量 |

## 监测点配置

在 `ken.py` 文件中修改 `meters` 列表可以添加或修改监测点：

```python
meters = [
    ('45976', '显兴水厂门口'),
    ('49071', '富临精工'),
    # 添加更多监测点...
]
```

## 注意事项

- 请确保网络可以访问上海肯特平台（http://www.shanghaikent.com:18601）
- 默认用户名：`scmy`，密码：`123456`
- 数据提取范围：最近20天

## License

MIT
