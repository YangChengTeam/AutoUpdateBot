from rapidocr_onnxruntime import RapidOCR
import time

class OcrEngine:
    _instance = None
    _model = None

    def __new__(cls, *args, **kwargs):
        """
        单例模式：确保整个程序运行期间，OCR 模型只加载一次。
        避免每次实例化 OcrEngine 都重新加载模型导致内存飙升和卡顿。
        """
        if cls._instance is None:
            cls._instance = super(OcrEngine, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        # 只有当模型未加载时才初始化
        if self._model is None:
            print("--> [Vision] 正在初始化 OCR 模型 (ONNX)...")
            # det_model, rec_model 使用默认即可，支持中英文数字
            # use_angle_cls=False: 模拟器截图通常是正的，不需要检测角度，关掉可以提速
            self._model = RapidOCR(use_angle_cls=False)
            print("    [Vision] 模型加载完毕")

    def detect(self, image):
        """
        执行文字检测
        :param image: OpenCV 格式的图像数组 (numpy array), 由 device.screenshot_cv2() 提供
        :return: list of dict, 格式如下:
                 [
                    {
                        'text': '更新',
                        'confidence': 0.98,
                        'box': [[x1,y1], [x2,y2], [x3,y3], [x4,y4]],
                        'center': (x, y)
                    },
                    ...
                 ]
        """
        if image is None:
            print("    [Vision] 警告: 输入图像为空")
            return []

        # 调用 RapidOCR
        # result 原始结构: [ [box, text, score], ... ]
        # elapsed 是耗时，我们不需要
        result, _ = self._model(image)

        if not result:
            return []

        clean_results = []
        for line in result:
            box = line[0]   # 四个角的坐标
            text = line[1]  # 文本内容
            score = line[2] # 置信度

            # 过滤掉置信度太低的垃圾数据 (可选，设为 0.5)
            if score < 0.5:
                continue

            # 预计算中心点，方便后续点击
            # 矩形中心公式: (x1+x3)/2, (y1+y3)/2
            center_x = int((box[0][0] + box[2][0]) / 2)
            center_y = int((box[0][1] + box[2][1]) / 2)

            clean_results.append({
                'text': text,
                'confidence': score,
                'box': box,
                'center': (center_x, center_y)
            })

        return clean_results

    @staticmethod
    def text_match(detected_text, keywords):
        """
        辅助函数：检查 OCR 结果中是否包含关键词列表中的任意一个
        """
        for kw in keywords:
            if kw in detected_text:
                return kw
        return None