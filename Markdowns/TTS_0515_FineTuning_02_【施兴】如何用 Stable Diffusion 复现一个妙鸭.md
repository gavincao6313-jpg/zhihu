# FineTuning_02_【施兴】如何用 Stable Diffusion 复现一个妙鸭

## 1. 视频元数据
- **推测主题：** 本视频详细介绍了Stable Diffusion图像生成技术，包括其核心原理、常用工具（如SD WebUI、Kohya）、模型（如Lora、ControlNet）的使用方法，并演示了如何在阿里云PAI-DSW平台上复现类似“妙鸭相机”的AI写真生成功能。
- **核心关键词：** Stable Diffusion, 妙鸭相机, AIGC, 文生图, 图生图, Lora, ControlNet, PAI-DSW, Kohya, 模型训练, 提示词, 扩散模型, AI写真。
- **适用受众/场景：** 对Stable Diffusion技术感兴趣的开发者、算法工程师、产品经理，以及希望在阿里云PAI-DSW平台上进行AIGC应用开发和模型训练的用户。

## 2. 核心知识字典（Glossary）
- **Stable Diffusion:** 一种流行的潜在扩散模型（Latent Diffusion Model），能够根据文本描述（Text-to-Image）或现有图像（Image-to-Image）生成高质量图像。其核心思想是在潜在空间进行扩散和去噪过程，大大降低了计算成本。
- **VAE (Variational Autoencoder):** 变分自编码器，在Stable Diffusion中用于将图像从像素空间编码到潜在空间（Encoder）和将潜在空间中的图像解码回像素空间（Decoder），从而在低维空间进行扩散操作，提高效率。
- **U-Net:** 一种经典的神经网络架构，因其U形结构而得名，常用于图像分割任务。在Stable Diffusion中，U-Net作为去噪网络，负责在潜在空间中迭代地去除噪声，逐步将随机噪声图转化为有意义的图像。
- **CLIP (Contrastive Language-Image Pre-training):** 对比语言-图像预训练模型，由OpenAI开发。它通过学习文本和图像之间的语义关联，将文本和图像映射到同一个嵌入空间，使得模型能够理解文本提示词并生成与之匹配的图像。
- **Lora (Low-Rank Adaptation of Large Language Models):** 一种针对大型模型进行高效微调的技术。它通过在预训练模型旁边添加少量可训练的低秩矩阵，而不是修改整个模型权重，从而在保持模型性能的同时，显著减少了训练所需的计算资源和时间，并生成小巧的模型文件。
- **ControlNet:** Stable Diffusion的一个插件，允许用户通过额外的输入（如边缘图、姿态骨架、深度图等）对图像生成过程进行更精细的控制，确保生成图像的结构、构图或姿态与输入条件保持一致。
- **Prompt (提示词):** 用户输入给Stable Diffusion模型的文本描述，用于指导图像生成的内容和风格。
- **Negative Prompt (反向提示词):** 用户输入给Stable Diffusion模型的文本描述，用于指定不希望在生成图像中出现的内容或特征，以提高生成图像的质量和符合度。
- **PAI-DSW (Data Science Workshop):** 阿里云提供的一个交互式开发环境，支持机器学习模型的开发、训练和部署，提供免费GPU算力。
- **Kohya:** 一个流行的开源工具，主要用于训练Stable Diffusion的Lora模型，提供图形用户界面（GUI）简化训练配置和过程。

## 3. 详尽内容解析（按时间线或章节）

### [00:00:00 - 00:02:32] 视频开场与讲师自我介绍
- **核心论点：** 讲师介绍了本次分享的主题Stable Diffusion及复现妙鸭相机，并进行了个人背景和工作职责的介绍。
- **详细展开：**
    - 讲师来自阿里云，是PAI机器学习算法平台工程和产品化应用的负责人。
    - 主要负责PAI平台侧的开发（如Notebook）、分布式训练推理，并在AutoML方面有经验。
    - 应用场景包括多模态（LLM、图像文本、图像视频打标、AIGC、人脸活体认证、LLM大模型训练推理落地）和推荐搜索广告（端到端推荐框架、EZRAC开源算法库、用户增长、RTA）。
    - 强调本次分享将侧重于图像文本多模态应用。
- **视觉/屏幕内容：**
    - 幻灯片标题：“如何用Stable Diffusion复现一个妙鸭”。
    - 讲师个人照片及简介：
        - 阿里高级资深专家
        - 现任PAI机器学习算法工程和产品化应用负责人
        - 负责深度学习训练推理平台工程以及基于平台之上的图像视频、智能推荐、用户增长算法和工程技术产品
        - 目标是支撑开发者和企业用户更好地使用云上产品，支撑大规模的AI训练和服务
        - 有过创业经验，对垂直行业创业有一定的思考
        - PAI平台：AI开发平台、分布式训练推理平台、AutoML
        - 多模态：图像视频分析、AIGC、SEKYC（人脸活体认证）、LLM大模型AI平台上的训练推理
        - 推荐搜索广告：端到端推荐框架、EasyRec开源算法库、用户增长+RTA

### [00:02:32 - 00:05:50] 课程大纲与初始准备：免费GPU获取
- **核心论点：** 课程将分为原理介绍、工具体验和进阶操作三大部分，并鼓励听众申请阿里云PAI-DSW的免费GPU以进行实践。
- **详细展开：**
    - **课程大纲：**
        1.  **原理介绍：** 生成示例、网络结构、名词解释、推理过程。
        2.  **工具体验：** 基本工具认识、打标工具、基底模型+Lora模型、ControlNet模型。
        3.  **进阶操作：** 训练自己的模型、基于PAI-DSW的妙鸭实现、其他插件。
    - **免费GPU申请：** 讲师推荐通过 `free.aliyun.com` 搜索DSW服务，新用户可免费领取GPU实例（如A10卡），可连续使用一个月。建议选择北京区域，因为上海、杭州区域GPU卡可能缺货。
    - **DSW实例创建步骤：** 登录 `free.aliyun.com` -> 搜索DSW -> 领取DSW -> 创建空间 -> 创建实例 -> 选择北京区域 -> 选择GPU规格（A10） -> 配置相关参数 -> 启动实例。
- **视觉/屏幕内容：**
    - 幻灯片“目录”：列出上述三大部分及其子项。
    - 幻灯片“初始准备”：显示 `https://free.aliyun.com` 和 `PAI-DSW`。
    - 阿里云免费试用页面截图，搜索“DSW”并显示“交互式建模 PAI-DSW”产品。
    - DSW实例创建页面截图，强调选择“北京”地域和“GPU规格”中的“NVIDIA A10”。
    - 命令行中显示镜像地址：`registry.cn-hangzhou.aliyuncs.com/mybigpai/photog_dsw:0.0.4`。
    - DSW实例启动界面，显示实例状态为“运行中”。

### [00:05:50 - 00:17:10] Stable Diffusion原理介绍与名词解释
- **核心论点：** 详细解释了Stable Diffusion的核心概念，包括Text-to-Image、Image-to-Image、网络结构（VAE、U-Net、CLIP）以及Lora模型的作用。
- **详细展开：**
    - **Stable Diffusion示例：**
        - **Text-to-Image (文生图):** 输入文本“paradise cosmic beach”，生成一张天堂般的海滩图片。
        - **Image-to-Image (图生图):** 在文生图的基础上，通过手绘草图（如船的轮廓）来控制生成图像中物体的位置和形状。
    - **Stable Diffusion网络结构：**
        - 训练过程：从原始图片 `x` 经过VAE Encoder `ε` 编码到潜在空间 `z`。在潜在空间中，通过Diffusion Process（不断加噪声）生成一系列噪声图 `zT`。同时，文本提示词通过Text Encoder `τθ` 编码为语义映射（Conditioning Semantic Map）。U-Net `θ` 结合噪声图和语义映射，迭代地进行去噪。最后，通过VAE Decoder `D` 将去噪后的潜在表示解码回像素空间，生成图片 `x̂`。
        - 推理过程：从随机噪声图开始，结合文本提示词，通过U-Net迭代去噪，最后通过VAE Decoder生成图片。
    - **名词解释：**
        - **模型 (Model):** 机器学习中学习一个函数 `Y=F(X)` 的过程。神经网络通过多层神经单元表征复杂的高阶关系。
        - **噪声 (Noise):** 在扩散模型中，通过逐步向清晰图像添加噪声，直到图像完全模糊，然后模型学习如何逆向去噪。
        - **U-Net:** 一种经典的神经网络，输入和输出尺寸相同，常用于图像分割，在Stable Diffusion中用于去噪。
        - **CLIP (Contrastive Language-Image Pre-training):** 预训练的语言模型，能将文本和图像编码到同一向量空间，实现多模态的表征关联。输出通常是77个Embedding，每个Embedding有768个维度。
        - **Text2Img / Img2Img:** 文生图和图生图是Stable Diffusion的两种主要应用场景。图生图是在给定初始图像的基础上进行生成。
        - **Lora (Low-Rank Adaptation of Large Language Models):** 一种高效微调大型模型的技术，通过在预训练模型旁添加小矩阵来学习任务特定参数，显著减少训练资源和时间。
- **视觉/屏幕内容：**
    - 幻灯片“Stable Diffusion”：展示“text -> image”和“text + image -> image”的示例图。
    - 演示WebUI界面，输入“paradise cosmic beach”，选择Anything模型，生成一张海滩图片。
    - 演示在WebUI中手绘船的轮廓，结合文本提示词生成带有船的海滩图片。
    - 幻灯片“Stable Diffusion - 网络结构”：展示Stable Diffusion的完整网络架构图，包括VAE Encoder/Decoder、Diffusion Process、Denoising U-Net、Text Encoder、Conditioning Semantic Map等组件。
    - 幻灯片“Stable Diffusion - 名词解释”：
        - “模型”部分展示了“Simple Neural Network”和“Deep Learning Neural Network”的对比图。
        - “噪声 (noise)”部分展示了从清晰小狗图片逐步加噪声到完全模糊的过程图。
        - “U-Net”部分展示了U-Net的结构图。
        - “CLIP”部分展示了Text Encoder和Image Encoder将文本和图像映射到同一Embedding空间，并说明了输出维度（77个Embedding，每个768维度）。
        - “Lora”部分展示了Lora的原理图，说明通过添加A、B两个小矩阵来适应预训练模型权重。

### [00:17:10 - 00:46:50] Stable Diffusion推理过程与工具体验
- **核心论点：** 详细讲解了Stable Diffusion的推理流程，并演示了SD WebUI的基本操作、模型获取、提示词编写技巧、Lora模型应用以及ControlNet的控制能力。
- **详细展开：**
    - **推理过程：**
        1.  **Prompt文本编码：** 输入文本提示词（Prompt），通过CLIP模型编码成Embedding向量。
        2.  **若干次采样：** 从随机噪声开始，结合文本Embedding，通过U-Net迭代去噪（多次采样）。
        3.  **进行解码：** 最终的潜在表示通过VAE Decoder解码成最终图像。
        - 代码示例展示了推理过程的三个主要步骤：Promote编码、噪声初始化、多次采样（U-Net去噪循环）、VAE解码。
    - **基本工具 - Diffusers库：** Hugging Face的Diffusers库是一个用于生成图像、音频、3D结构等的最先进扩散模型的Python库。代码示例展示了如何使用Diffusers库进行文生图操作。但提到国内用户可能遇到连接问题。
    - **基本工具 - SD WebUI：**
        - **基本概念：** 文生图 (txt2img) 和 图生图 (img2img)。
        - **输入参数：** 提示词 (Prompt)、反向提示词 (Negative Prompt)、采样方法 (Sampler)、迭代步数 (Steps)、相关性 (CFG Scale/Guidance)、随机种子 (Seed)、生成批次/每批数量 (Batch size)、图像尺寸 (Width/Height)。
        - **提示词技巧：** 演示了如何使用预设的正面提示词（如“Best Quality, Masterpiece, Ultra High Resolution, Original Photo, Cinematic Lighting”）和反向提示词（如“nsfw, low quality, extra arms”）来提高生成质量和避免不良内容。
        - **模型切换：** 演示了如何切换不同的基底模型（如Anything V4.5、Disney Cartoon）来生成不同风格的图片。
    - **模型获取 - C站/Hugging Face：**
        - **C站 (Civitai.com):** 社区驱动的模型分享平台，提供各种风格的模型（Checkpoint、Lora等），用户可根据图片风格下载。
        - **Hugging Face:** 另一个重要的模型库，当C站访问不便时可作为替代。
        - 演示了在C站上搜索并下载Lora模型（如“Lah Mysterious | SDXL”），以及通过C站助手插件在WebUI中直接下载模型。
    - **Lora模型应用：**
        - 演示了如何加载和使用Lora模型（如“李逍遥”风格的Lora），通过在Prompt中添加触发词（Trigger Word）来激活特定风格。
        - 演示了训练自己的柯南Lora模型，并用其生成类似柯南风格的图片。
    - **ControlNet模型：**
        - **作用：** 提供对图像生成过程的精细控制，例如保持人物姿态、物体轮廓等。
        - **示例：**
            - 输入一张房间照片，通过ControlNet的Halfline预处理器提取线条，然后结合“room”提示词生成不同风格的房间。
            - 通过HED（Holistically-Nested Edge Detection）提取边缘图，生成不同风格的人脸。
            - 用户可以手绘简单图形（如船的轮廓），ControlNet会根据轮廓生成相应物体。
        - **演示：**
            - 在WebUI中启用ControlNet，上传一张空白图并手绘船的轮廓，选择Canny预处理器和模型，结合“paradise cosmic beach, with a boat”提示词生成带有船的海滩图片。
            - 演示了ControlNet的权重（Control Weight）参数，控制对输入图像的遵循程度。
            - 举例说明ControlNet在创意设计中的应用，如将“X”字母融入街景或人物肖像中。
- **重要金句/原话：**
    - “模型跟我们以前做的那些机器学习数据Y角里面经常提到的学一个函数，就是Y等于fx。”
    - “像Stable Diffusion做的作用就是随机给一张就是都是噪音的图，然后再加一个文本的输入，这两个作为输入，然后去不停的深层深层深层深层这个图。”
    - “这个Web UI它的一些这里可以塞选模型，那我自己比较用的比较多的可能是这个Anything的模型。”
    - “这个词还是挺难编的，所以就有了下一个，就是他们就有一些工具，你可以用一些工具来帮你生成这个词。”
    - “基本上做Stable Deficient写Wavvi，大家都知道它。”
    - “这个做的比较好的，是它的插件机制，你可以自己装很多很多插件。”
    - “这个就直接影响你这个出图的时间。”
    - “这个值呢越高，就是越贴近于贴近于一般是到25还是到30吧，顶就是建就是封顶，然后一般就在七左右七八左右。”
    - “为了为了出同一个图，你确把他每次都出同一个图，那你就把随机种子固定。”
    - “所以大家现在能看到很多图像，其实都有基底能大概确定一个风格。”
    - “这个模型怎么下载，一种方法是点进去，然后这里可以打漏的。”
    - “这个罗拉的训练是根据你给的一些数据来的。”
    - “我自己在整理这个课件的时候，我自己都觉得，就是光是教大家怎么体验这些词好像挺没意思的。”
    - “那外乎就是在这里面，难道一节课都在高方大家怎么写这个promote，对吧。”
    - “就人物的框架，或者说人物的方向，给我去生成一下，那这个怎么办？这个就有了后面这个control net。”

### [00:46:50 - 01:11:01] 进阶操作：训练自己的Lora模型
- **核心论点：** 演示了如何使用Kohya工具训练自己的Lora模型，包括数据准备、打标、训练配置和模型导出。
- **详细展开：**
    - **Kohya工具介绍：** Kohya是一个开源的Lora模型训练工具，由日本人开发，提供GUI界面简化训练流程。
    - **训练流程：**
        1.  **准备数据：** 收集用于训练的图片（例如小蓝的图片）。
        2.  **打标 (Captioning)：** 使用Kohya内置的BLIP或WD1.4 Tagger等工具对图片进行自动打标，生成描述图片内容的文本文件（.txt）。打标时可以在标签前添加触发词（如“小蓝”），方便后续生成时触发特定风格。讲师强调，为了更好的训练效果，打标结果需要人工精修。
        3.  **训练配置：**
            - **选择基底模型：** 选择一个预训练的Stable Diffusion模型作为基础（如Anything模型）。
            - **设置训练数据路径：** 指定打标后的图片目录。
            - **设置输出路径和模型名称：** 定义训练好的Lora模型保存位置和文件名。
            - **参数配置：** 设置Epoch数量（例如4遍）、优化器（如AdamW8bit）、精度（如fp16）。
        4.  **启动训练：** 点击“Train model”开始训练。训练过程会显示进度条和日志。
        5.  **模型导出与使用：** 训练完成后，会生成`.safetensors`格式的Lora模型文件。将该文件拷贝到SD WebUI的`models/Lora`目录下，刷新WebUI即可使用。
    - **演示：**
        - 使用Kohya的Captioning工具对“小蓝”的图片进行打标，生成包含“小蓝, one girl, long hair, blue eyes, school uniform, tie, window”等描述的文本文件。
        - 配置Kohya训练界面，选择Anything模型作为基底，指定训练数据和输出路径，设置Epoch为4，优化器为AdamW8bit，精度为fp16。
        - 启动训练，并展示训练日志和进度。
        - 演示将训练好的小蓝Lora模型拷贝到SD WebUI的Lora目录，并在WebUI中选择该Lora模型，结合提示词“小蓝, one boy, pointing the viewer”生成小蓝风格的图片。
- **视觉/屏幕内容：**
    - 幻灯片“进阶操作 - 如何训练自己的模型”：显示Kohya的训练界面截图。
    - 命令行界面展示Kohya的启动命令和日志输出。
    - Kohya WebUI界面，展示“Captioning”和“Training”标签页。
    - “Captioning”页面中，输入图片目录`xiaolan_lora`，选择`wd1.4_tagger`模型进行打标，并添加前缀“xiaolan”。
    - 命令行显示打标过程和生成的`.txt`文件内容，例如`xiaolan, one girl, solo, long hair, blue eyes, medium hair, school uniform, tie, window, cho art style`。
    - “Training”页面中，配置Source model为`models/anything`，Image folder为`xiaolan_lora`，Output folder为`xiaolan_230831`，Model output name为`xiaolan`。
    - 配置Parameters，Epochs设置为4，Optimizer选择`AdamW8bit`，Mixed precision选择`fp16`。
    - 命令行显示训练命令和日志，包括加载模型、数据处理、训练进度条等。
    - SD WebUI的Lora模型选择界面，显示已加载的“conan”、“sword_and_fairy_lixiaoyao”、“xiaolan”等Lora模型。
    - 演示在SD WebUI中选择“xiaolan”Lora模型，输入“xiaolan, one boy, pointing the viewer”生成图片。

### [01:11:01 - 01:39:05] 基于PAI-DSW的妙鸭实现与其他插件
- **核心论点：** 演示了如何在阿里云PAI-DSW上实现类似妙鸭相机的AI写真生成流程，并介绍了SD WebUI的一些实用插件。
- **详细展开：**
    - **PAI-DSW上的妙鸭实现 (PAIYA)：**
        - **环境准备：** 下载核心代码库（`train_kohya_DSW.zip`），解压并软链预训练权重（`model_data`）。
        - **模型下载与加载：** 从ModelScope下载并加载人脸检测、人脸质量、皮肤修复、人脸融合、人脸识别等多个模型。
        - **用户参考图选择：** 从用户上传的写真图片中，通过Face ID相似度、图片质量分、人脸角度分等综合评分，选择一张最佳人脸图片作为后续换脸的基准图（Root Image）。
        - **证件照生成：** 将选定的Root Image与预设的证件照模板进行融合，生成一张具有用户脸部的证件照。此过程涉及OpenPose和Canny等ControlNet预处理，以及两次人脸融合（一次粗略，一次精修）。
        - **写真生成：** 将生成的证件照作为输入，结合预设的写真模板，通过Stable Diffusion和ControlNet（OpenPose、Canny）生成最终的AI写真。
        - **训练自己的Lora模型：** 提供了在PAI-DSW上训练自己Lora模型的代码和步骤，与前面Kohya的演示类似，但强调了人脸预处理（裁剪出人脸区域）以提高训练效果。
    - **其他插件：**
        - **XYZ Plot：** 用于批量测试不同参数组合（如CFG Scale、Seed、Sampler等）对生成结果的影响，并以网格形式展示。
        - **Prompt Generator：** 帮助用户生成更丰富、更详细的提示词。
        - **Segment Anything：** 图像分割工具。
        - **Fabric：** 纹理生成工具。
        - **Model Downloader：** 方便从C站等下载模型。
    - **学习资源：** 推荐B站、C站、Hugging Face、ModelScope、ChatGPT等平台获取学习资料和工具。
- **视觉/屏幕内容：**
    - 幻灯片“进阶操作 - 基于PAI-DSW的妙鸭PAIYA”：展示了杨幂的图片作为输入，经过“人脸检测-选择最优人脸-证件照生成-写真生成”的流程图，最终生成一张古风写真。
    - PAI-DSW Notebook界面，展示了Python代码单元格。
    - 代码中包含`wget`下载`train_kohya_DSW.zip`，`unzip`解压，`ln -s`创建软链。
    - Python代码加载ModelScope模型，包括`face_detection`、`face_quality_assessment`、`face_skin_retouching`、`face_fusion`、`face_recognition`等。
    - 代码计算Face ID Score、Quality Score、Face Angles，并选择最佳Root Image。
    - 演示了将杨幂人脸融合到证件照模板上，生成一张杨幂的证件照。
    - 演示了将杨幂证件照融合到古风写真模板上，生成一张杨幂的古风写真。
    - 幻灯片“其他插件”：列出XYZ Plot、Prompt Generator、Segment Anything、Fabric、Model Downloader等插件。
    - SD WebUI界面，演示XYZ Plot脚本，选择CFG Scale参数，从1到10，步长为3，生成三张不同CFG Scale的图片（1.0, 5.5, 10.0），并以网格形式展示。
    - SD WebUI界面，演示Prompt Generator插件，输入“One Boy”，生成多个详细的提示词。
    - 幻灯片“Q&A”：展示二维码，供观众提问。
- **重要金句/原话：**
    - “这个是领领专利的地方，然后这边是就生成一个羊蜜，羊蜜加这个图，生成一个把羊蜜的脸放上去的图。”
    - “这个主要是使用那个stable division的技术，因为他里面是用stable division加control net再加loader这几个技术，再加一些打磨院上面有的一些模型，那个model scope上有的的一些模型生产的。”
    - “我通过三个分就代码里面主要是这边我们会把所有的图片都辨历一下，然后里面去算三个分，主要是这三个分，一个是Face ID的分，就他跟那个亚密相互之间最像的那个分，然后质量分，还有一个是角度分。”
    - “这个是裁检出来的，出户裁检出来的图，这个是最终参与到罗拉训练里面的图。”
    - “这个进度调内部默认设置的800 step，所以一只要15分钟左右。”
    - “我发现这个代码特别好。”

### [01:39:05 - 01:46:53] 问答环节与总结
- **核心论点：** 回答了观众关于模型保存、生成图片版权、ControlNet训练、参数转代码等问题，并对课程内容进行了简要回顾。
- **详细展开：**
    - **模型保存：** ModelScope可以保存项目。
    - **防止生成色情图片：** 可以通过反向提示词（如“nsfw”）和启用Safe Checker功能来避免。Safe Checker会将识别出的色情图片变成黑图。
    - **ControlNet训练：** ControlNet模型可以训练，讲师团队曾用于视频风格转化。
    - **参数转代码：** SD WebUI的“图片信息”功能可以显示生成图片的详细参数，用户可以将这些参数手动复制到Python代码中（如Diffusers库），替换Prompt和Negative Prompt等。
    - **中文Prompt：** SD WebUI有中文翻译插件，但核心模型仍基于英文提示词。
    - **AI生成图片版权：** 目前版权问题尚无明确说法，Stable Diffusion生成的图片通常带有水印（可关闭），版权归属仍是争议点。
    - **连环画生成：** 建议使用ControlNet进行多图控制，以实现连环画效果。
- **视觉/屏幕内容：**
    - 幻灯片“Q&A”页面，右侧显示聊天区的问题。
    - SD WebUI的“图片信息”标签页，展示了生成图片的详细参数，包括Prompt、Negative Prompt、Sampler、Steps、CFG Scale、Seed等。
    - 讲师展示了自己用AI生成的头像。

## 4. 遗留问题与下一步行动（如有）
- **遗留问题：**
    - AI生成图片的版权归属问题目前尚无明确法律规定。
    - Stable Diffusion模型在生成手部细节时仍可能存在问题。
    - 训练Lora模型时，如何精修自动打标的标签以获得最佳效果。
    - ControlNet的各种预处理器和模型参数组合众多，如何找到最优配置。
- **下一步行动：**
    - 鼓励用户利用阿里云PAI-DSW的免费GPU资源，亲自动手实践Stable Diffusion的文生图、图生图、Lora模型训练和ControlNet应用。
    - 建议用户探索C站、Hugging Face、ModelScope等平台获取更多模型和学习资源。
    - 推荐使用ChatGPT等工具辅助生成提示词和编写代码。
    - 探索SD WebUI的更多插件，如XYZ Plot进行参数调优，Prompt Generator辅助提示词编写，Segment Anything进行图像分割等。
    - 深入研究ControlNet的更多功能，例如多层ControlNet控制，以及如何训练自定义的ControlNet模型以实现视频风格转化等高级应用。