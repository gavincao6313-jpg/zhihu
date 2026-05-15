# AutoGPT_01_【丛鑫、卢雅西】XAgent 原理、技术与应用

## 1. 视频元数据
- **推测主题：** 本视频详细介绍了XAgent，一个由清华大学和面壁智能联合开发的大模型智能体框架，旨在通过双循环机制、丰富的工具集成、统一的Function Calling语言和人机协作能力，自主解决复杂任务，并探讨了其技术原理、部署实践及相关前沿研究。
- **核心关键词：** XAgent, 大模型智能体, AI Agent, Function Calling, 双循环机制, 工具调用, 任务规划, ReAct, Docker, 人机协作, 开源模型, ToolLLM, JuDec, CREATOR, ProAgent
- **适用受众/场景：** 适用于对AI Agent、大模型应用开发、LLM技术原理、开源模型集成以及自动化解决方案感兴趣的开发者、研究人员和技术爱好者。视频旨在解决大模型在处理复杂任务时缺乏自主性、规划僵硬、不稳定不安全、工具调用不统一以及人机交互有限等痛点。

## 2. 核心知识字典（Glossary）

*   **AI Agent (智能体):** 在人工智能中，一个智能体(IA)是一个以智能方式行动的实体；它感知其环境，自主采取行动以实现目标，并通过学习或获取知识来提高其性能。
*   **XAgent:** 一个由清华大学CHU-NLP实验室和面壁智能共同联合研发的、能够自主完成复杂任务的大模型智能体框架。它基于GPT等强大大模型，通过双循环机制、海量工具集成、统一的Function Calling语言和新型人机协作模式，提升解决真实复杂任务的能力。
*   **双循环机制 (Dual-Loop Mechanism):** XAgent的核心运行机制，包括一个负责高级任务管理和分配的“外循环”（Planning Agent）和一个专注于每个子任务的低级执行和优化的“内循环”（Tool Agent）。
*   **Function Calling (函数调用):** OpenAI推出的一种功能，允许大模型根据用户输入智能地选择并调用外部函数。在XAgent中，所有Agent的操作（包括规划、工具调用和反思）都采用Function Calling方式实现，以确保结构化、统一化和无缝化的操作。
*   **ReAct (Reasoning and Acting):** 一种Agent决策框架，通过“思考（Thought）-推理（Reasoning）-计划（Plan）-批评（Criticism）-行动（Action）”的循环，使Agent能够进行多步骤的工具调用和决策，并根据工具返回结果进行迭代和反思。

## 3. 详尽内容解析（按时间线或章节）

### [00:00:03 - 00:06:27] 课程开场与嘉宾介绍

- **核心论点：** 本次直播是1、2、3期学员及外部朋友共同参与的Agent专题分享，重点介绍XAgent项目，旨在提供理论与实践相结合的深度内容，并鼓励社区贡献。
- **详细展开：**
    *   主持人开场，欢迎所有学员和外部朋友参与，强调这是首次将多期学员汇集到同一直播间。
    *   本次直播聚焦于当前工业界、学术界和投资界都非常看好的Agent领域，将进行非常实操的分享。
    *   主持人提醒观众在提问时控制消息条数，以便老师更好地捕捉问题并进行互动。
    *   针对不同期学员的学习基础，主持人建议三期学员若遇到困难可在学员群中寻求助教帮助。
    *   有观众提问XAgent是否是GPTS的超级GPT，主持人澄清GPTS本质是包装，RAG是核心，Agent取决于Instruction，而XAgent能对接更多工具，远超GPTS目前开放的少量接口。
    *   XAgent是开源项目，可在GitHub上搜索到。
    *   XAgent支持最新模型，需要Docker环境。
    *   主持人介绍两位主讲嘉宾：丛森老师（清华大学计算机系博士，面壁智能XAgent项目核心成员）和卢雅西老师（清华大学计算机系博士后，面壁智能XAgent项目核心成员）。两位老师共同分享，旨在提供全面讲解并与社区互动，鼓励大家使用XAgent并为社区贡献。
- **视觉/屏幕内容：**
    *   [00:00:00] 视频开始，两位讲师坐在桌前。
    *   [00:00:06] 讲师们开始讲话，画面显示直播间界面。
    *   [00:00:46] 画面显示讲师们在等待。
    *   [00:05:09] 幻灯片切换到标题页：**XAgent: 面向复杂任务的大模型智能体**。下方显示“清华大学计算机系博士后 丛森”、“面壁智能XAgent项目核心成员 卢雅西”、“2023.11.16”。左上角有清华大学校徽，右上角有“面壁智能 ModelBest”Logo。
    *   [00:06:20] 两位讲师入座，丛森老师开始讲解。
- **重要金句/原话：**
    *   “今天我们特别邀请到的两位大咖，就现在最应该说最前沿的，不管是在工业界、学术界还是投资界都最被看好的Agent这个方面进行非常非常实操的一个分享。” [00:00:53 - 00:01:08]
    *   “XAgent它能够对接的各种工具什么之类的，其实是相比GPTS应该也是毫不逊色的，现在甚至应该能对得更多。” [00:03:40 - 00:03:51]

### [00:06:27 - 00:07:59] XAgent概述与议程

- **核心论点：** XAgent是清华大学和面壁智能联合研发的大模型智能体，旨在通过升级GPT系列大模型，提升其解决真实复杂任务的能力。本次分享将涵盖XAgent概述、技术原理、实践和相关技术分享。
- **详细展开：**
    *   丛森老师开始介绍XAgent，强调其是清华CHU-NLP实验室和面壁智能联合研发的“面向复杂任务的大模型智能体”。
    *   XAgent的目标是基于GPT等强大大模型，将其升级为智能体，以提升解决现实生活中复杂任务的能力，解决痛点问题。
    *   本次分享的四个主要部分：
        1.  XAgent概述（背景介绍）
        2.  XAgent技术原理介绍
        3.  XAgent实践（环境配置、使用、开发）
        4.  XAgent相关技术分享
- **视觉/屏幕内容：**
    *   [00:06:27] 幻灯片显示标题页：**XAgent: 面向复杂任务的大模型智能体**。
    *   [00:07:27] 幻灯片切换到目录页：
        *   XAgent概述
        *   XAgent技术原理介绍
        *   XAgent实践
        *   XAgent相关技术分享

### [00:07:59 - 00:15:53] Agent概念及发展历程

- **核心论点：** AI Agent的概念由来已久，经历了规则式、强化学习式的发展，在大模型出现后，LLM-based Agent成为新的研究范式，具备通用智能和自主行动能力。
- **详细展开：**
    *   **Agent的定义：** AI Agent的概念早在上世纪80年代末就已提出。根据维基百科定义，AI Agent是一个智能实体，能够感知环境，自主采取行动以实现目标，并通过学习或获取知识来提高性能。它包含接收环境信息、决策、采取行动、自主化和达成目标等环节。
    *   **Agent的发展阶段：**
        1.  **早期（规则式）：** 主要基于规则(rule-based)，智能水平受限，需要专家人工编写规则来定义Agent的行为。
        2.  **深度学习时代（强化学习RL-based）：** 随着机器学习、统计学习、深度学习兴起，强化学习Agent得到快速发展，如AlphaGo。AlphaGo在围棋等特定领域展现出超越人类的智能（2016年以4:1战胜李世石），但其主要局限性在于**缺乏通用性**，只能在特定领域表现出色，难以迁移到其他领域。
        3.  **大模型时代（LLM-based）：** 随着ChatGPT等大模型在2022年11月推出，Agent研究范式发生巨大变化。大模型展现出强大的通用智能，能够完成写邮件、写材料等多种任务。LLM-based Agent指一个使用大语言模型驱动，可以观察周遭环境并利用工具作出行动以达到目标的自主实体。
- **视觉/屏幕内容：**
    *   [00:07:59] 幻灯片标题“Agent介绍”。右侧配图是一个Agent模型图，显示了Agent与Environment之间的Action、Percept、Sensor、Actuator交互循环，以及Agent内部的What is the current state?、What action to take?、Update knowledge等模块。
    *   [00:08:56] 幻灯片更新，左侧列出Agent发展阶段：
        *   早期：基于规则(rule-based)，智能水平十分受限。
        *   深度学习兴起后：基于强化学习(RL-based)的Agent在某些特定领域展现出超越人类的智能（围棋、游戏）。
        *   当下：基于大模型(LLM-based)的Agent研究逐渐成为当下火热的新范式。
    *   [00:10:32] 幻灯片更新，左侧详细描述早期Agent：
        *   在AI领域，Agent研究可追溯到上世纪80年代末。
        *   比较系统的提出来自于 Marvin Minsky 1986《Society of Mind》。
        *   Agent只能完成简单、机械的任务。
        *   右侧配图是Marvin Minsky的《Society of Mind》书籍封面。
    *   [00:13:37] 幻灯片更新，左侧详细描述深度学习时代Agent：
        *   在深度学习时代，强化学习在Agent领域得到了广泛的研究与应用。
        *   Agent可以自主探索与学习中获得可以超越人类的智能水平（围棋、游戏）。
        *   但是RL-based Agent仅适用于特定领域，**缺乏通用性**。
        *   右侧配图是AlphaGo的Logo和2016年AlphaGo与李世石的围棋比赛画面。
    *   [00:14:53] 幻灯片更新，左侧详细描述大模型时代Agent：
        *   在大模型出现后，因大模型所展现出的通用智能，LLM-based Agent成为了新范式。
        *   LLM-based Agent指一个使用大语言模型驱动可以观察周遭环境并利用工具作出行动以达到目标的自主实体。
        *   下方配图是一个LLM-based Agent的架构图，核心是Agent，连接着Tools（Calendar, Calculator, CodeInterpreter, Search, ...more）、Memory（Short-term memory, Long-term memory）和Planning（Reflection, Self-critic, Chain of Thought, Subgoal decomposition）。Agent通过Action与Environment交互。讲师用激光笔标注了Memory、Tools、Planning。
- **重要金句/原话：**
    *   “它可以在一些特定领域里能表现出一些超越人类的智能。” [00:10:02 - 00:10:04] (指强化学习Agent)
    *   “但是它会有个非常大的局限性，就是它缺乏通用性。” [00:13:56 - 00:13:58] (指强化学习Agent)
    *   “大模型所展示的通用性能，其实给我们其实留下了非常深刻的影响。” [00:15:17 - 00:15:22]

### [00:15:53 - 00:23:02] LLM-based Agent的关键能力

- **核心论点：** LLM-based Agent需要具备工具使用、推理规划和记忆机制三大核心能力，才能真正实现自主行动和目标达成。
- **详细展开：**
    *   **1. 工具 (Tools):**
        *   大模型（如ChatGPT）本质是对话模型，只会“说”，缺乏“动手”能力。
        *   结合外部工具（如搜索引擎、订票软件、各种APP和API）能让大模型“长出双手”，与外界环境互动并影响环境。
        *   **例子：** 旅游规划。如果只有ChatGPT，它只能写攻略；如果结合工具，它可以搜索景点、预订机票酒店、安排行程。
    *   **2. 推理规划 (Planning):**
        *   解决复杂任务需要多步决策，这考验大模型的推理与规划能力。
        *   **例子：** 旅游规划。Agent需要推理用户喜好（人文/自然风光）、规划交通（火车/飞机时刻表）、住宿（酒店安排）、景点开放时间，并串联起来形成充实的行程。
    *   **3. 记忆 (Memory):**
        *   Agent需要像人类一样，从经验中学习，利用历史信息指导当前决策。
        *   **短期记忆 (Short-term memory):** 存储最近发生的事情，如上一步操作及结果，影响当前决策。
        *   **长期记忆 (Long-term memory):** 存储更长远的信息，如昨天、上周获得的信息，用于全局规划，避免短视决策。
- **视觉/屏幕内容：**
    *   [00:15:53] 幻灯片显示LLM-based Agent的架构图，讲师用激光笔标注了“Tools”、“Planning”、“Memory”及其子模块。
    *   [00:16:16] 讲师用激光笔圈出“Tools”模块。
    *   [00:19:31] 讲师用激光笔圈出“Planning”模块。
    *   [00:20:50] 讲师用激光笔圈出“Memory”模块，并分别指向“Short-term memory”和“Long-term memory”。

### [00:23:02 - 00:26:32] 现有LLM-based Agent的局限性

- **核心论点：** 现有的大模型Agent普遍存在自主性不足、规划僵硬、不稳定不安全、智能体语言不统一以及人机交互有限等问题。
- **详细展开：**
    *   **1. 有限的自主性：** 很多Agent研究（如MetaGPT）过度依赖专家先验知识，需要人工编写SOP（标准操作流程）或Pipeline来指导大模型执行任务，Agent的自主性受限。
    *   **2. 僵硬的任务规划：** 难以解决复杂任务，缺乏全局性规划能力。例如，LangChain的Step by Step决策方式难以从全局角度进行任务规划，存在缺陷。
    *   **3. 不稳定和不安全：** 大模型与工具结合后可与环境互动，可能产生危险行为。例如，在代码中执行`rm -rf`等破坏性命令。因此，需要对Agent的行为进行安全性和稳定性控制。
    *   **4. 不统一的智能体语言：** 不同环节（推理规划、记忆机制、工具调用）可能采用不同机制实现，导致各模块割裂，难以协同工作，限制了智能体整体性能。
    *   **5. 有限的人机交互：** 在不确定环境中，Agent无法“闷头”执行，需要与人协同配合。现有Agent缺乏主动寻求人类反馈或指导的能力。
- **视觉/屏幕内容：**
    *   [00:23:02] 幻灯片标题“Agent介绍”，左侧列出五点局限性，右侧配图是一个冒烟、损坏的机器人，象征Agent的局限和问题。
        *   有限的自主性：依赖人类专家的先验知识
        *   僵硬的任务规划：难以解决复杂任务
        *   不稳定和不安全：可能做出危险行为
        *   不统一的智能体语言：限制智能体性能
        *   有限的人机交互：在不确定环境中做出非预期行为

### [00:26:32 - 00:28:27] XAgent的特点

- **核心论点：** XAgent旨在克服现有Agent的缺陷，通过六大亮点实现自主完成复杂任务的智能体。
- **详细展开：**
    *   **1. 无需专家知识：** XAgent是一个通用的AI智能体，无需提前输入特定领域的专家知识。
    *   **2. 动态的任务规划：** 在执行过程中，XAgent会根据当前执行状况，迭代优化任务规划。
    *   **3. Docker执行环境：** 所有XAgent行为被限定在Docker容器内执行，确保对外部环境的影响受限，保证行为安全。
    *   **4. 海量的工具：** XAgent集成了大量工具，极大地扩展了其能力边界，使其能完成更多任务。
    *   **5. 统一的智能体语言 (Function Calling):** 规划和工具执行都采用统一的Function Calling方式实现，确保不同环节有机结合。
    *   **6. 新型的人机交互/协作：** XAgent能与人紧密配合，共同完成任务，结合Agent和人类的优势，提高任务解决效率。
- **视觉/屏幕内容：**
    *   [00:26:32] 幻灯片标题“XAgent介绍”，左侧列出XAgent的六大特点，右侧配图是一个六边形环绕的XAgent Logo，每个六边形代表一个特点：
        *   无需专家知识
        *   动态任务规划
        *   Docker执行环境
        *   海量工具
        *   统一智能体语言
        *   新型人机交互

### [00:28:27 - 00:39:59] XAgent技术原理：双循环机制与工具服务器

- **核心论点：** XAgent采用“规划（外循环）+执行（内循环）”的双循环机制，并通过ToolServer支持多种工具，确保安全、高效和模块化地完成复杂任务。
- **详细展开：**
    *   **双循环机制：**
        *   **外循环 (Outer Loop) - PlanAgent：** 负责高级任务管理和分配，进行动态规划和迭代优化。
            *   **初始规划生成：** 将用户提出的复杂任务拆分成若干子任务，形成任务队列。
            *   **迭代规划优化：** 在执行完每个子任务后，对执行结果进行反思，并依此修订规划，包括：
                *   **Subtask Split (子任务拆分):** 当某个子任务比预期困难时，将其进一步拆分为更小的子任务。
                *   **Subtask Deletion (子任务删除):** 当任务比预期简单时，删除不必要的后续步骤。
                *   **Subtask Modification (子任务修改):** 根据执行情况调整后续子任务的方向或做法。
                *   **Subtask Addition (子任务增加):** 当发现需要额外步骤才能推进任务时，增加新的子任务。
            *   **例子：** 解决“24点游戏”任务，PlanAgent会拆分为：理解游戏规则、编写Python代码、测试代码、优化代码。
        *   **内循环 (Inner Loop) - ToolAgent：** 专注于每个子任务的低级执行和优化。
            *   **工具检索：** 根据子任务目标和性质，从工具库中检索相关工具。
            *   **ReAct方式调用工具：** 采用“思考（Thought）-行动（Action）”循环，连续调用工具完成子任务。每一步先思考（Thought），再采取行动（Action），并根据行动结果继续思考。为了提升性能和可解释性，ReAct还会生成四个字段：
                *   **Thought (思考):** 对当前情况进行分析，决定下一步行为。
                *   **Reasoning (推理):** 解释采取该行为的原因。
                *   **Plan (计划):** 采取当前行为后，后续还需要做什么。
                *   **Criticism (批评):** 当前行为的潜在风险、不可控因素及改进空间。
            *   **Reflection (反思)：** 对任务完成结果进行反思，总结经验（哪些工具好用，哪些失败），并将反馈传递给外循环的PlanAgent，帮助优化后续规划。
    *   **ToolServer (工具服务器)：** 支持多种工具，实现安全、高效和模块化。
        *   **ToolServerNode：** 每个任务执行（工具调用）的真实环境，基于Docker容器，确保工具调用的安全性，将危险行为限制在沙箱内。
        *   **ToolServerMonitor：** 监视每个Server Node的执行状态，确保有效执行。
        *   **ToolServerManager：** 管理Docker容器的生命周期，包括创建和关闭Node。
        *   **支持的工具包括：**
            *   **FileSystemEnv：** 文件读写。
            *   **PythonNotebook：** 编程，如编写算法解决24点游戏。
            *   **WebEnv：** 搜索引擎，网页浏览，获取额外信息。
            *   **ExecuteShell：** Shell命令执行，如创建文件、执行命令。
            *   **RapidAPIEnv：** 集成16000+个真实世界API，涵盖金融、健康、医疗、运动、新闻等49种大类。
            *   **AskHumanForHelp：** 主动向人类寻求帮助。
- **视觉/屏幕内容：**
    *   [00:28:37] 幻灯片标题“XAgent介绍”，配图是XAgent的双循环机制图。左侧是User Query，进入Outer Loop (PlanAgent)，PlanAgent进行Task Decomposition，生成Subtasks。Subtasks进入Inner Loop (ToolAgent)，ToolAgent进行Tool Dispatch & Tool Execution，产生Observation，并进行Reflection，将Feedback反馈给Outer Loop。Outer Loop根据Feedback进行Plan Refinement，最终输出Final Result。
    *   [00:29:52] 幻灯片更新，左侧描述Outer Loop (PlanAgent)的“初始规划生成”和“迭代规划优化”，右侧配图是XAgent前端界面，显示了“Outer Loop: Task 1”下的四个子任务列表：
        1.  尝试理解24点游戏规则。
        2.  编写24点游戏的Python demo。
        3.  测试24点游戏的Python demo。
        4.  优化24点游戏的Python demo。
    *   [00:34:00] 幻灯片更新，左侧描述Inner Loop (ToolAgent)的“检索相关工具”、“ReAct方式调用工具”和“对任务完成结果进行reflection”，右侧配图是XAgent前端界面，显示了“Inner Loop: Subtask 2”的执行过程，包括Thought、Reasoning、Plan、Criticism字段，以及Using Tool、Command Name、Arguments、Execution Result、Command Status等信息。
    *   [00:36:33] 幻灯片更新，左侧描述Inner Loop (ToolAgent)在调用工具时需要给出Thought、Reasoning、Plan、Criticism。右侧配图与上一帧相同，红色框线圈出了Thought、Reasoning、Plan、Criticism字段。
    *   [00:38:00] 幻灯片更新，左侧描述ToolServer支持多种工具，实现安全、高效和模块化，并列出支持的工具。右侧配图是Docker的Logo。讲师用激光笔标注了“ToolServerNode”、“ToolServerMonitor”、“ToolServerManager”和“支持的工具包括”列表。

### [00:39:59 - 00:46:12] XAgent技术原理：统一智能体语言与人机协作及评测

- **核心论点：** XAgent通过统一的Function Calling语言实现各模块的无缝衔接，并具备AskHumanForHelp能力，实现高效人机协作。实验评估显示XAgent性能显著优于GPT-4和AutoGPT。
- **详细展开：**
    *   **统一的智能体语言：Function Calling**
        *   XAgent中所有Agent操作均采用Function Calling方式实现，包括规划（Planning）、工具调用（Tool）和反思（Reflection）。
        *   **结构化：** 统一操作格式，使Agent行为更可控，减少错误。
        *   **统一化：** 系统设计统一，降低复杂度，提高鲁棒性。
        *   **无缝化：** 不同工具间可流畅衔接，相互配合工作。
    *   **AskHumanForHelp：主动向人类寻求帮助**
        *   XAgent可以主动与用户进行交互，并接受人类的干预和指导请求，针对性修改自身行为。
        *   **用户直接修改规划：** 用户可以直接修改XAgent制定的计划（如Plan），Agent会根据修改后的规划调整行为，纠正Agent的偏差。
        *   **Agent主动请求反馈：** XAgent会根据当前执行情况，主动向人类请求反馈、建议或指导。
        *   **例子：** 预订餐馆任务。如果用户提供信息不足（预算、口味、距离等），XAgent会主动调用AskHumanForHelp工具，询问用户更明确的需求，以更好地满足用户。
    *   **XAgent评测：**
        *   **实验评估标准：** 基于一系列基准测试评估XAgent在推理、规划和使用外部工具的能力。
        *   **与GPT-4和AutoGPT对比：** XAgent性能远超两者。
            *   与GPT-4对比：在QA（知识问答）、Code（代码）、Math（数学）、Reasoning（推理规划）等能力上，XAgent（基于GPT-4升级）性能有显著提升。
            *   与AutoGPT对比：在Data Analysis（数据分析）、Math（数学）、Search and Report（搜索报告）、Life Assistant（生活助理）、Coding & Development（编程开发）等场景下，XAgent的成功率均高于AutoGPT。
- **视觉/屏幕内容：**
    *   [00:40:00] 幻灯片标题“XAgent介绍”，左侧描述统一智能体语言：Function Calling，右侧配图是一个代码片段，显示了OpenAI API的`chat/completions`接口调用，其中定义了`functions`参数，包含`name`、`description`、`parameters`等字段，红色框线圈出了Function Calling的JSON结构。
    *   [00:42:30] 幻灯片更新，左侧描述AskHumanForHelp功能，右侧配图是XAgent前端界面，显示了Agent的规划（Plan）和用户修改规划的输入框，以及Agent主动询问用户“What kind of restaurant do you prefer?”的对话框。红色框线圈出了用户修改规划的输入框和Agent主动提问的对话框。
    *   [00:43:32] 讲师用激光笔圈出Agent主动询问用户需求的对话框。
    *   [00:43:39] 讲师用激光笔圈出用户可以修改Agent规划的输入框。
    *   [00:43:47] 讲师用激光笔圈出Agent主动询问用户需求的对话框。
    *   [00:44:32] 幻灯片标题“XAgent评测”，左侧列出实验评估标准，右侧是两个图表：
        *   左侧柱状图对比了XAgent和GPT-4在不同任务（PromptQA, HotpotQA, MBPP, MATH, GSM8K）上的Pass Rate (%)，XAgent的蓝色柱子普遍高于GPT-4的红色柱子。
        *   右侧堆叠柱状图对比了XAgent和AutoGPT在不同任务（Data Analysis, Math, Search and Report, Life Assistant, Coding & Development）上的成功率，XAgent的蓝色部分显著多于AutoGPT的红色部分。

### [00:46:12 - 00:55:27] XAgent实践：环境搭建与基本使用

- **核心论点：** XAgent是开源项目，通过Docker环境可快速搭建和运行，支持OpenAI API Key配置，并提供前端界面进行交互。
- **详细展开：**
    *   **环境搭建前提：**
        *   安装Docker环境。
        *   安装docker-compose。
        *   安装Git。
    *   **构建步骤：**
        *   克隆XAgent仓库：`git clone https://github.com/OpenBMB/XAgent.git`。
        *   参考快速开始内容进行构建。
        *   一行命令即可完成构建：`docker-compose up --build`。
        *   启动前端界面：`docker exec XAgent-Server systemctl start nginx`。
    *   **API Key配置：**
        *   需要填写`config`文件，提供OpenAI API Key。
        *   必须提供`gpt-3.5-turbo-16k`的Key，推荐使用`gpt-4`的Key。
        *   可以通过修改`model`参数来选择使用的模型（如将`gpt-3.5-turbo-16k`改为`gpt-4`）。
        *   未来将支持本地开源模型（如基于CodeLlama的preview版本，预计下周发布），但效果可能不如GPT-4。
        *   配置完成后，在`.env`文件中修改`config`文件路径。
    *   **运行演示：**
        *   启动服务后，进入前端界面（`localhost:8080`）。
        *   选择Agent类型（目前只开放了XAgent的简单版本）。
        *   选择运行模式：`Auto Model`（自主决定下一步）或`Manual Model`（需要手动介入）。
        *   输入Query，如“计算100以内所有质数”。
        *   后台服务器开始运行，可在Log中查看执行信息。
        *   前端界面会显示Inner Loop的中间状态，如执行Python代码，并可查看代码内容。
        *   XAgent与ChatGPT最大的区别在于它带有Code Interpreter，并支持多种其他工具。
- **视觉/屏幕内容：**
    *   [00:46:12] 幻灯片标题“XAgent搭建”，列出前提和构建步骤。
        *   前提：安装docker环境、docker-compose、git。
        *   构建步骤：克隆XAgent仓库（`https://github.com/OpenBMB/XAgent`），参考快速开始内容构建，一行命令`docker-compose up --build`，启动前端界面`docker exec XAgent-Server systemctl start nginx`。
    *   [00:46:38] 讲师切换到GitHub页面，显示OpenBMB/XAgent仓库。
    *   [00:47:03] 讲师点击README.md中的中文文档链接。
    *   [00:47:20] 讲师在README.md中滚动，展示安装Docker和构建镜像的说明。
    *   [00:48:06] 讲师切换到XAgent前端运行演示视频。视频中显示了XAgent的Web UI，用户输入Query，Agent开始执行，并显示Inner Loop的执行步骤，包括Thought、Reasoning、Plan、Criticism、Using Tool等。
    *   [00:49:01] 演示视频中点击“View Code”，显示Agent生成的Python代码：
        ```python
        def is_prime(num):
            if num < 2:
                return False
            for i in range(2, int(num**0.5) + 1):
                if num % i == 0:
                    return False
            return True

        primes = [num for num in range(2, 101) if is_prime(num)]
        print(primes)
        ```
    *   [00:49:24] 讲师切换回PPT，然后切换到VS Code界面，展示`config.yaml`文件，其中包含OpenAI API Key的配置项，以及`model`参数。
    *   [00:52:40] 讲师在VS Code中展示`.env`文件，修改`CONFIG_FILE`路径。
    *   [00:53:04] 讲师在终端执行`docker-compose up --build -d`命令。
    *   [00:53:27] 讲师展示`running_records`文件夹，其中存储了XAgent的中间执行状态。
    *   [00:54:03] 讲师在终端执行`docker ps`命令，显示运行中的Docker容器（xagent-server, mongodb, tool-server-manager, tool-server-monitor, tool-server-node）。
    *   [00:55:27] 讲师切换到XAgent前端界面，显示Agent选择（XAgent）、Model选择（Auto/Manual），以及Query输入框。

### [00:55:27 - 01:13:16] XAgent实践：工具开发与核心代码逻辑

- **核心论点：** XAgent的ToolServer封装了多种基础和高级工具，并支持用户自定义工具。其核心代码逻辑基于外循环的任务分解和内循环的ReAct执行，通过Function Calling实现各模块的协同。
- **详细展开：**
    *   **ToolServer工具详解：**
        *   `tool_server`文件夹管理工具服务器代码，`tool_server_node`是真实执行环境。
        *   `core/env`目录下包含主要工具：
            *   `file_system_env.py`: 文件读写。
            *   `python_notebook.py`: 执行Python代码，支持视觉结果返回（如绘图）。
            *   `web_env.py`: 搜索引擎（如Bing Search），网页浏览，信息解析。
            *   `shell_command_executor.py`: 执行任意Shell命令，可用于安装软件、管理系统等，但需注意安全风险。
            *   `rapid_api_env.py`: 集成RapidAPI平台上的16000+真实世界API。
            *   `ask_human_for_help.py`: 主动向人类寻求帮助。
    *   **开发新工具：** 简单地定义一个Python文件，导入必要变量和`@tool_wrapper`装饰器，即可定义新工具。
    *   **XAgent内部代码逻辑：**
        *   **入口：** 通过`run.py`文件启动命令行运行，或通过`xagent_server`的`task_handler.py`处理前端请求。
        *   **外循环 (`outer_loop_async_run`):**
            *   在`task_handler.py`中，首先进行`initial_plan_generation`，将用户Query分解为子任务。
            *   然后进入循环，逐个处理子任务。
            *   每个子任务完成后，会进行`plan_refine`，根据内循环的反馈对任务规划进行迭代优化（增、删、改、拆分）。
        *   **内循环 (`inner_loop_async_run`):**
            *   在`inner_loop_search_algorithms/ReAct.py`中实现。
            *   **工具获取：** 首先根据子任务目标获取相关工具（`retrieve_tool`），工具数量可在`config.yaml`中配置。
            *   **ReAct搜索算法：** 模型根据当前任务和历史信息，通过Function Calling决定下一步动作（Thought, Reasoning, Plan, Criticism），选择工具并执行。
            *   **工具执行：** 调用`tool_call_handle.py`中的`function_call`方法，向ToolServer发送请求并获取结果。
            *   **结果总结与反思：** 通过`summarize_action.py`中的`summarize_action_process`函数，将历史执行步骤和工具返回结果进行总结（Summary）和反思（Reflection），反馈给模型，帮助其判断下一步动作。
            *   **失败处理：** 如果内循环执行失败，会返回外循环进行`plan_refine`，修正任务规划。
    *   **Function Calling的重要性：**
        *   Function Calling是XAgent的核心，所有操作都通过它实现。
        *   它允许自定义参数，使模型能够输出结构化的思考、原因、计划和批评，并决定下一步的工具调用和参数。
        *   这些参数的准确性直接影响Agent的执行效果，对模型的高级智能要求很高。
- **视觉/屏幕内容：**
    *   [00:57:52] 讲师切换到VS Code界面，展示`tool_server`文件夹结构，并打开`tool_server/core/env`目录下的`file_system_env.py`、`python_notebook.py`、`web_env.py`、`shell_command_executor.py`等文件。
    *   [00:58:59] 讲师展示`python_notebook.py`文件，提到支持视觉结果返回。
    *   [01:00:42] 讲师展示`web_env.py`文件，提到其搜索引擎和浏览功能。
    *   [01:01:18] 讲师展示`shell_command_executor.py`文件，强调其执行任意Shell命令的能力，并提醒安全注意事项。
    *   [01:02:31] 讲师演示如何创建新工具，在`tool_server/core/env`下新建`test.py`文件，并编写简单代码：
        ```python
        from tool_server.tool_code.tool_wrapper import tool_wrapper

        @tool_wrapper()
        def test_tool():
            return "Hello from test tool!"
        ```
    *   [01:03:21] 讲师切换到`run.py`文件，说明其是命令行运行入口。
    *   [01:04:05] 讲师切换到`xagent_server/workflow/task_handler.py`文件，并用激光笔圈出`self.outer_loop_async_run()`。
    *   [01:04:51] 讲师用激光笔圈出`self.plan_agent.initial_plan_generation()`，表示任务分解。
    *   [01:05:17] 讲师点击进入`inner_loop_async_run`函数。
    *   [01:05:51] 讲师展示`task_handler.py`中的`self.config.rapidapi_retrieve_tool_count`配置项，用于控制工具检索数量。
    *   [01:07:25] 讲师展示`inner_loop_search_algorithms/ReAct.py`文件，并用激光笔圈出`function_call = self.llm.chat_completion_with_plugin(...)`，说明通过Function Calling获取工具调用。
    *   [01:08:19] 讲师用激光笔圈出`tool_output = tool_call_handle(...)`，说明工具执行。
    *   [01:08:57] 讲师用激光笔圈出`summarize_action_process(...)`，说明对执行结果进行总结。
    *   [01:09:52] 讲师展示`a_functions/summarize_action.yaml`文件，定义了`summarize_action`函数，包含`summary`和`failed_reason_and_reflection`等参数。
    *   [01:10:50] 讲师回到`task_handler.py`，用激光笔圈出`self.plan_agent.plan_refine_model()`，表示任务修正。
    *   [01:12:02] 讲师展示`plan_agent.py`中的`plan_refine_mode`函数，其中包含`split`、`add`、`delete`、`exit`等操作，用于迭代优化任务规划。

### [01:13:16 - 01:36:52] XAgent开源计划与相关技术分享

- **核心论点：** XAgent团队致力于开源模型适配、提升Agent能力，并构建了包括WebCPM、BMTools、ToolLLM、JuDec、CREATOR、ProAgent在内的Agent生态，旨在推动AI Agent技术普惠社会。
- **详细展开：**
    *   **XAgent开源计划：**
        *   **开源模型适配：** 短期内将精力集中在适配开源模型上。
            *   第一期计划适配Llama模型，为其添加Function Calling能力，使其更好地支持XAgent场景。
            *   下周将发布基于CodeLlama的preview版本，支持本地部署。
            *   承认开源模型在推理、规划、总结反思等高级能力上与GPT-4仍有差距，但会持续优化。
            *   ChatGLM模型适配将由团队成员负责。
        *   **项目报错与社区贡献：** 项目仍处于初期阶段，欢迎用户在GitHub上提交issue、discussion，提出建议或贡献代码。
        *   **1.0版本发布：** 预计在一到两周内正式发布1.0版本，将有全新的Web界面，支持文件修改、图片显示等更多功能。
        *   **多智能体框架对比：** 将发布博客文章，对比XAgent与AutoGen、OpenAgents等其他框架的区别。
    *   **XAgent相关技术分享（前沿探索）：**
        *   **WebCPM：大模型使用搜索引擎**
            *   中文领域首个基于交互式网页搜索的问答开源模型框架（ACL国际顶会论文）。
            *   构建了包含5500对高质量问题-答案及十万多真实用户网页搜索行为的LFQA数据集。
            *   实现大模型对搜索引擎的精细控制（上下翻页、滚动、点击、摘要），在30%+情况下达到或超越人类搜索水平。
        *   **BMTools：工具学习开源工具包**
            *   支持文生图模型、搜索引擎、恶意查询等30+主流工具的统一调用框架。
            *   一键接入本地模型，对接现有工具，使用户更方便地将大模型适配特定工具。
            *   **例子：** 分析新冠相关文献，生成总结报告。
        *   **ToolLLM：提高大模型工具使用能力**
            *   构建大规模开源高质量工具学习数据集ToolBench，以增强大模型的工具使用能力，并提升其工具泛化能力。
            *   支持16000+个真实世界API，支持单工具与多工具场景。
            *   基于ToolBench数据训练后的模型能高效泛化到未见过的新API并高效调用，工具使用能力接近ChatGPT。
        *   **JuDec：大模型自主决策**
            *   旨在解放大模型的自主决策能力，摆脱对专家经验的依赖。
            *   让大模型主动探索决策路径，并根据探索历史自我评价，形成自经验，从而找到优化决策。
            *   采用Elo Rating算法对大模型探索经验进行量化。
            *   在不引入额外知识的情况下，大模型可获得性能与效率的双重优势（解决任务成功率更高，API调用次数更少）。
        *   **CREATOR：大模型创造工具**
            *   解决大模型工具使用能力受限于工具自身功能和可用性的问题。
            *   在面临困难任务时，不一定有合适的工具。
            *   工具创造：让大模型基于现有工具创造新工具来解决困难问题，通过封装和升级现有工具，提高解决任务的效率。
        *   **ProAgent：大模型智能体赋能自动化**
            *   传统RPA（Robotic Process Automation）通过构建Workflow实现机械任务自动化，但无法处理动态决策任务，且Workflow构建需人工参与。
            *   Agentic Process Automation：让Agent根据人类需求自动构建Workflow，同时将Agent嵌入Workflow中进行动态决策。
            *   提升Workflow处理复杂任务的能力，从日常机械任务扩展到需要智能的任务。
    *   **XAgent团队与生态：**
        *   XAgent是由清华大学THUNLP实验室与面壁智能共同创立的大模型智能体，也是研究大模型智能体的开放社区。
        *   参与机构：清华大学、面壁智能、人民大学、OpenBMB、MIT、Google。
        *   开源项目地址：`https://github.com/OpenBMB/XAgent`。
        *   案例展示地址：`https://x-agent.net/`。
        *   博客地址：`https://blog.x-agent.net`。
        *   **产学研结合构建大模型生态：** 形成“三驾马车”布局：
            *   **XAgent：** 大模型驱动的超强AI智能体应用框架。
            *   **AgentVerse：** 大模型驱动的多智能体通用平台（研究Agent协作、沟通）。
            *   **ChatDev：** 大模型驱动的多智能体协作开发框架（聚焦软件开发场景）。
        *   愿景：智周万物，让AI智能体连接万物 (Internet of Agents)，普惠社会，提升生产力。
- **视觉/屏幕内容：**
    *   [01:13:16] 讲师切换到GitHub页面，展示OpenBMB/XAgent仓库的Issues页面，并点击“XAgent V1.0 Launch Update and Next Steps #182”的Issue。
    *   [01:13:50] 讲师展示Issue内容，其中列出了XAgent项目计划：开源模型适配（Llama）、1.0版本发布（全新Web UI）、多智能体框架对比博客等。
    *   [01:19:41] 讲师切换到VS Code界面，展示`xagent_server/a_functions/request/openai.py`文件，其中包含`chat_completion_request`函数，用于调用OpenAI的Chat Completion接口。
    *   [01:20:23] 讲师展示`xagent_server/a_functions/request/obj_generator.py`文件，其中包含`obj_generator`函数，用于根据`request_type`调用不同的请求接口。
    *   [01:21:10] 讲师展示`xagent_server/assets/config.yaml`文件，其中包含`request_type`的配置项。
    *   [01:22:58] 讲师切换到`xagent_server/assets/tasks.yaml`文件，展示了多个复杂任务的英文描述，例如“Please assist me in compiling a list of top 5 universities globally for a master's program in Data Science...” (查找全球顶尖大学数据科学硕士项目信息)。
    *   [01:26:47] 幻灯片标题“相关技术分享”。
    *   [01:26:57] 幻灯片显示“WebCPM: 大模型使用搜索引擎”的介绍，包括ACL论文信息、数据集构建和平台支持的操作（搜索、翻页、滚动、点击、摘要）。配图是WebCPM的UI界面，左侧是Query输入和搜索结果，右侧是Agent可执行的操作列表。
    *   [01:27:34] 讲师切换到WebCPM的演示视频，展示Agent自主进行网页搜索、点击、摘要的过程。
    *   [01:28:03] 幻灯片更新，显示WebCPM在30%+情况下与用户使用搜索引擎水平持平或超越，学习到人类的搜索策略。配图是WebCPM的搜索界面。
    *   [01:28:06] 幻灯片显示“BMTools: 工具学习开源工具包”的介绍，包括支持30+主流工具、一键接入本地模型等。配图是BMTools的GitHub页面、PPT、数据库图标和论文截图。
    *   [01:28:31] 讲师切换到BMTools的演示视频，展示Agent使用工具进行文献分析和总结。
    *   [01:30:12] 幻灯片显示“ToolLLM: 提高大模型工具使用能力”的介绍，包括构建ToolBench数据集、支持16000+真实API等。配图是ToolLLM的GitHub页面、论文截图和模型训练流程图（API Collection -> Instruction Generation -> Answer Annotation -> ToolBench -> SFT LLaMA）。
    *   [01:31:00] 幻灯片更新，显示ToolLLM的UI界面和性能评估图表。图表对比了不同模型（ChatGPT-DFSOT, ChatGPT-ReAct, ToolLLaMA-DFSOT, ToolLLaMA-ReAct等）在API调用限制下的Win Rate。
    *   [01:32:23] 幻灯片显示“JuDec: 大模型自主决策”的介绍，包括解放自主决策能力、主动探索决策路径、自我评价等。配图是决策树的示意图，展示了Agent如何通过探索和评估选择路径。
    *   [01:33:00] 幻灯片更新，显示JuDec采用Elo Rating算法量化探索经验，并在不引入额外知识的情况下获得性能与效率双重优势。配图是实验结果表格（Model, Pass Rate (%)）和效率实验结果图表（Efficiency experimental results on various API call limits）。
    *   [01:33:17] 幻灯片显示“CREATOR: 大模型创造工具”的介绍，包括大模型工具使用能力受限、创造新工具解决困难问题等。配图是CREATOR的架构图，展示了Agent如何通过Abstraction、Reasoning、Execution、Notification等步骤创造和使用工具。
    *   [01:34:18] 幻灯片显示“ProAgent: 大模型智能体赋能自动化”的介绍，对比了RPA和Agentic Process Automation，强调Agent自动构建Workflow和动态决策的能力。配图是RPA和Agentic Process Automation的流程对比图。
    *   [01:34:43] 幻灯片标题“XAgent Team”，列出团队成员、开源项目地址、案例展示地址、博客地址和联系方式。
    *   [01:35:25] 幻灯片标题“产学研结合构筑大模型生态”，配图是三环图，中心是“面壁智能”，外围是“THUNLP”和“OpenBMB”。右侧列出THUNLP、面壁智能、OpenBMB的简介。
    *   [01:35:47] 幻灯片标题“大模型驱动的AI Agent‘三驾马车’”，配图是ChatDev、XAgent、AgentVerse三个模块相互连接的示意图。
    *   [01:36:31] 幻灯片标题“智周万物 让AI智能体连接万物 Internet of Agents”。
    *   [01:36:49] 幻灯片显示“Thank You”和讲师姓名。

### [01:36:52 - 02:06:32] Q&A 环节

- **核心论点：** 讲师们回答了关于XAgent开源模型集成、能力提升、长期记忆、任务拆解、代码纠错、工具选择和上下文管理等问题，强调了Function Calling和模型基础能力的重要性。
- **详细展开：**
    *   **开源模型集成：**
        *   下周将公开XAgent结合内部自研大模型的preview版本，支持本地化部署，欢迎试用CodeLlama等开源模型。
        *   AI Agent方向与大模型自身能力高度绑定，团队正在研究如何提升开源模型在Agent方面的能力，使其接近GPT-4水平。
    *   **XAgent提升大模型能力：**
        *   XAgent的架构（特别是推理过程，如JuDec算法）能够提升大模型在下游任务上的性能。
        *   但需考虑token数量和成本，研究如何在更少token下保持更好性能。
    *   **自动化训练大模型：**
        *   XAgent目前有能力自动化训练Bert模型。例如，它可以自主从网络获取电影评论数据集，编写训练代码，保存checkpoint，进行推理预测，整个过程都是自主完成。
        *   在训练过程中，XAgent会遇到并自行解决问题，如安装缺失的Python包（NLTK），修改执行报错的代码，直到代码正确运行。
    *   **长期记忆：**
        *   XAgent 1.0版本将正式支持长期记忆功能，通过VectorDB存储历史经验、反思和技能。
        *   在执行后续任务时，Agent会提取历史经验，具备“自如演化”的能力。
    *   **任务拆解：**
        *   任务拆解过程是Agent自主完成的，根据自身判断、推理和规划决定拆解成多少子任务以及每个子任务的具体内容。
        *   人机交互允许用户动态修改Agent的规划，提供反馈进行纠正。
        *   目前限制子任务拆解深度最多三层，以避免过于复杂。
        *   任务规划能力是比工具调用更困难的能力，更考验大模型的基础智能水平。
    *   **工具调用与选择：**
        *   工具分为内部工具（文件读写、Python调用）和外部工具（RapidAPI等）。
        *   Agent在规划时会考虑手头已有的工具，并根据自身能力进行任务拆解。
        *   在内循环中，Agent会根据子任务目标进行工具检索（Tool Retrieval），从工具库中匹配最相关的工具。
        *   团队专门训练了模型来提升工具检索能力，效果优于OpenAI的Embeddings模型。
    *   **上下文长度与Summary：**
        *   XAgent集成了Summary功能，对历史信息进行总结，避免上下文过长。
        *   在执行每个子任务过程中，会累积大量信息（如网页浏览内容），Summary机制会提取最关键、对解决当前任务最有帮助的信息，作为下一个子任务的输入。
        *   Summary的总结过程也是XAgent自主完成的，针对任务进行总结，而非泛泛总结，以避免信息丢失。
    *   **文生图实现：**
        *   文生图可以通过将图像生成模型作为工具集成到ToolServer中，Agent调用该工具生成图片。
        *   也可以通过Python代码（如数据分析绘图）的方式实现图像生成，XAgent已在案例中展示了生成柱状图、折线图的能力。
    *   **开源模型Function Calling能力：**
        *   目前国内开源模型在Function Calling的灵活性和智能化方面尚未达到OpenAI的水平。
        *   XAgent的Function Calling复杂度高，需要模型具备高级智能才能正确决策参数。
        *   呼吁国内模型厂商重视并支持更高级的Function Calling功能，使其成为智能体与逻辑代码交互的桥梁。
    *   **ToolLLM上下文支持：** ToolLLM基于Llama模型训练，其上下文长度与原始Llama模型保持一致。团队也在自研模型（如CPM）上进行增量SFT，以提升其Agent能力。
- **视觉/屏幕内容：**
    *   [01:39:38] 讲师切换到PPT，展示JuDec: 大模型自主决策的决策树示意图。
    *   [01:42:12] 讲师切换到VS Code界面，展示`xagent_server/data_structure/vector_db.py`文件，其中包含`VectorDBInterface`类，用于管理向量数据库。
    *   [01:43:12] 讲师切换到`xagent_server/workflow/task_handler.py`文件，用激光笔圈出`self.plan_agent.plan_refine_model()`。
    *   [01:44:52] 讲师用激光笔圈出`self.config.max_plan_refine_depth`，表示任务拆解深度限制。
    *   [01:51:56] 讲师切换到`inner_loop_search_algorithms/ReAct.py`文件，用激光笔圈出`message_sequence.append(Message("user", new_subtask_prompt))`和`function_call = self.llm.chat_completion_with_plugin(...)`。
    *   [01:53:10] 讲师切换到`xagent_server/a_functions/pure_functions/task_handle_functions.yaml`文件，展示`submit_subtask`函数定义，其中包含`success`、`conclusion`、`milestones`、`submit_type`、`error`等参数，以及`for_plan_refine`参数。
    *   [01:59:29] 讲师切换到`xagent_server/agent/summarize.py`文件，用激光笔圈出`summarize_action_process`函数。
    *   [02:01:57] 讲师切换到`x-agent.net`网站，展示案例页面，其中包含数据分析的图表（小提琴图）。
    *   [02:04:00] 讲师切换到PPT，展示ToolLLM的数据收集与模型训练图，并用激光笔圈出“Tool Retrieval”模块。
    *   [02:06:15] 幻灯片显示联系方式：Email: `xagentteam@gmail.com`，微信公众号: `OpenBMB`。

## 4. 遗留问题与下一步行动（如有）

*   **开源模型适配：**
    *   下周将发布XAgent结合CodeLlama的preview版本，支持本地部署，但性能可能与GPT-4有差距。
    *   团队将持续优化XAgent在3.5及开源模型上的性能，并为Llama模型添加Function Calling能力。
    *   ChatGLM模型的适配工作正在进行中。
    *   将发布关于XAgent与多智能体框架对比的博客文章。
*   **XAgent 1.0版本：** 预计在一到两周内正式发布，将提供全新的Web界面，支持文件修改、图片显示等更多功能。
*   **长期记忆功能：** 1.0版本将正式集成长期记忆功能，通过VectorDB存储历史经验和技能，使Agent具备自如演化能力。
*   **社区贡献：** 欢迎用户在GitHub上提交issue、discussion，提出建议或贡献代码，共同推进AI Agent方向的研究。
*   **国产模型支持：** 呼吁国内模型厂商重视并提升其在Agent场景下的能力，特别是Function Calling的灵活性和智能化，以便XAgent能更好地适配国产大模型。
*   **性能与效率优化：** 持续研究如JuDec算法等，在保证性能的同时，减少token消耗，提高效率。
*   **工具创造能力：** 进一步探索让大模型基于现有工具创造新工具的能力，以更高效地解决问题。