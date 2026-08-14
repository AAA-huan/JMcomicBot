# PR 说明：优化下载与转PDF内存占用（img2pdf直嵌 + 限制并发）

## 背景

实际运行中 bot 在 4GB 内存机器上下载漫画并转 PDF 时，内存经常飙升到 2.5GB+，导致 WSL 出现 OOM，进程被内核杀死、bot 崩溃。转 PDF 是主要峰值来源。

## 根因

`src/download/manager.py::_convert_chapter_to_pdf` 使用 Pillow 合并生成 PDF：

```python
first_image.save(temp_pdf_path, save_all=True, append_images=other_images)
```

- Pillow 会把 `append_images` 中所有图片**一次性解码全部驻留内存**，直到保存结束。
- 每张图片 `.convert("RGB")` 触发真实解码，全分辨率像素累计驻留，章节页数越多峰值越高。

另外 `option.yml` 未配置下载线程数，jmcomic 走默认值 `image=30`（同时下载 30 张图片）+ `photo=CPU线程数`，多任务叠加进一步推高内存。

## 改动内容

### `src/download/manager.py`（核心）
- 转 PDF 改用 **img2pdf** 直嵌图片，逐张流式写入，不再全量解码驻留：
  ```python
  with open(temp_pdf_path, "wb") as pdf_file:
      img2pdf.convert(
          image_files,
          outputstream=pdf_file,
          rotation=img2pdf.Rotation.ifvalid,
      )
  ```
- JPEG 为 direct 嵌入（不做像素解码，纯 IO 流式写入），内存占用与章节页数基本无关。
- 移除原来的 `pip install Pillow` 运行时兜底（依赖已由 requirements 声明保证）。
- 保留原有的收集排序、temp/final 路径移动、异常兜底与日志逻辑。

### `requirements.txt`
- 新增 `img2pdf>=0.5.0`（自动携带 pikepdf、lxml）。

### `option_example.yml` / `option.yml`
- 新增下载并发限制（原默认 `image:30 / photo:全核`，4GB 机器上过高）：
  ```yaml
  download:
    threading:
      image: 8   # 同时下载图片数
      photo: 2   # 同时下载章节数
  ```

### 新增测试 `tests/test_download_manager.py`
- 覆盖 PDF 转换（JPG/PNG 均产出合法 `%PDF`）、空章节返回 None、`option.yml` threading 配置解析。

## 效果

- 转 PDF 峰值内存大幅下降（见验证）。
- 下载阶段并发从 30 张降为 8 张，章节串行化为 2，避免内存叠加。
- 换用 img2pdf 后转换耗时也更短（流式写入 + JPEG 零解码）。

## 验证

- 单元测试：`tests/test_download_manager.py`（4 个用例）+ `tests/test_websocket_client.py`（9 个），`pytest` 13 passed。
- `pyright`：本次改动文件 0 errors。
- `pylint`：本次改动文件通过，仅剩既有函数（`_process_download_task`）历史警告，非本次引入。
- `black`：本次改动文件格式通过。
- **内存实测**（100 张 1400×2000 JPEG，独立进程对比）：
  - 旧实现（Pillow 全量加载）：峰值 RSS **≈1096 MB**
  - 新实现（img2pdf 直嵌）：峰值 RSS **≈54 MB**
  - 新实现 PDF 经 pikepdf 校验 100 页完整，文件正常可读。