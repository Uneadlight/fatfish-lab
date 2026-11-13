r"""候选路线库的域数据（第 0 步 · 加壳）。

从 tier.py 原样搬出来，一个字都没改 —— 拆文件时文本会变（import / 缩进 / 换行），
所以验收不看文本，看 `D:\work\.tmp\tier-baseline.py --check` 的 10 条输入
是否仍命中同样的域 / 路线 / 档位 / 组合。
"""

PATH_OPTIONS = [
    {
        "domain": "3D / 建模 / 渲染",
        "words": ("3D", "3D建模", "几何建模", "渲染", "微缩", "场景", "glb", "材质",
                  "写实", "照片级", "贴图", "纹理", "建模"),
        "routes": [
            # 2026-11-10 血泪排序：先问「要写实吗」。要写实 → 走 E（AI 出模型），
            # 不要 → 才轮到 B/D 手搓。那天我从 B 开始手搓 8 小时，交出去被一句
            # 「只是把大体的一个形状做出来了」打回；而 E 那条路 3 分钟就能出
            # 31 万顶点带贴图的真模型。**路径选错，后面所有努力都是沉没成本。**
            ("E", "AI 生图定美术 → image-to-3D 出模型（写实首选）",
             "真贴图、真细节、几十万顶点；`lab i23d` 一条命令，3–25 秒出白模、"
             "3 分钟出带 19 MB 贴图的精细模型；写实度是手搓模型的几十倍",
             "要公网图片 URL（base64 会被拒 UrlIllegal）；图床只剩 uguu.se / litterbox 可用；"
             "并发默认 1（第二个报 RequestLimitExceeded.JobNumExceed）；要 key 要网要钱；"
             "产出是 OBJ zip（obj+mtl+texture png），得自己转 GLB",
             "GLB 里 materials 数 > 5 且带贴图 URI；`dump-mats.py` 看 baseColor 不是纯白"),
            # 以下 F/G/H/I 是「交付前关卡」，不是「怎么造」——和 A/B/C/D 不在一个维度：
            # F 管性能、G 管材质、H 管光、I 管产物。选了任何一条造法，这四关都要过。
            ("F", "【关卡】合批降 draw call（任何 3D 交付的必过项）",
             "卡不卡由 draw call 数决定，不由顶点数决定（1544 mesh / 77k 顶点 = 1544 次/帧，就是卡）；"
             "Blender 侧按材质 `bpy.ops.object.join()`、three.js 侧 `InstancedMesh`（同几何不同变换）",
             "**必须建模阶段就做，建完再补等于重写生成脚本**。三个硬约束："
             "①join 的下界是材质数不是 1——glTF 一个 primitive 只挂一个材质，本场景 24 材质 → 24 次，"
             "再降只能做纹理图集；②`export_gpu_instances=True` 只在「同父节点 + 共享同 mesh + 数量≥2」时生效，"
             "把尺寸烘进 mesh（`o.data.transform(Matrix.Diagonal(...))`）的话它一个都不认；"
             "③两种假合批会静默失效——`mergeGeometries` 属性不一致返回 `null` 不抛错，"
             "`BatchedMesh` 缺 `WEBGL_multi_draw` 时退化成逐次 render",
             "**唯一权威口径 `renderer.info.render.calls`：1544 → 期望 ≈24，合格线 ≤300，`triangles` 应不变**。"
             "但**读这个数本身有坑**：`renderer.info.render` 每帧开头会被清零，在帧边界外（CDP 求值 / 控制台 / "
             "rAF 之外的任意时刻）读到的永远是残值 `calls=1`——会得出「合批没生效」的错误结论。必须 "
             "`renderer.info.autoReset = false;` + 渲染循环里 `renderer.info.reset(); composer.render(); "
             "window.__CALLS__ = renderer.info.render.calls;`，读缓存的 `window.__CALLS__`（2026-11-10 卡了两轮）；"
             "GLB 里 `nodes`/`meshes`/`primitives` 三个数都等于零件数就是「一个零件一个 object」的指纹"),
            ("G", "【关卡】材质贴图化（墙面不是纯色平面）",
             "`bpy.ops.object.bake` 把程序化节点烘成图（1024² / **0.54 s**）；"
             "或 numpy 预生成颜色数组（**0.07 s**，零依赖）；烘完必须把 Image Texture 连回 Base Color",
             "**glTF 导出器不支持程序化节点**——带 noise 的材质 baseColor 会静默导成纯白 (1,1,1)，"
             "不烘就是白模；体积：无贴图 GLB 1,152 B → 烘 PNG 545 KB → WebP q90 **13,908 B（-97.4%）**。"
             "三个坑：①bake 没设 active image node 时 4.5.15 **静默成功、像素全 0**（不报错）；"
             "②本机 TEMP 被 ACL 挡，导 WebP/JPEG 前要改 `TEMP`；③`etc1s`/`uastc` 缺 KTX-Software；"
             "④**CanvasTexture 的 `canvas.height` 必须等于 `fillRect` 的高度**——写 `cv.height = 160` 却只 "
             "`fillRect(0, 0, 1024, 96)`，下面 64 像素就是全透明的，招牌看起来「被截断」/「下半截是空的」；"
             "同一块 canvas 上画边框时 `strokeRect` 也要贴着真实高度画（2026-11-10 连踩两次）",
             "GLB 里 materials 带贴图 URI 且 baseColor 不是纯白；贴图文件存在且体积合理（几百 KB 不是 0 B）；"
             "**`gltf-transform inspect` 的 `TEXTURES: 0` 就是「没有材质细节」的客观判据**（2026-11-10 实测我那份街景 GLB "
             "22 材质 / 0 贴图 = 全是纯色，用户当场判「只是把大体的形状做出来了」）"),
            ("H", "【关卡】灯光与色调映射（别再把数值拍到墙上试）",
             "先定 tone mapping 再定灯：`ACESFilmicToneMapping` + exposure 按 `2^(-stops)` 推、锚点 1.0"
             "（压 0.75 档 = 0.594）；HDRI + PMREM 当反射底色，`envMapIntensity` 默认 1.0 靠反推",
             "**bloom `threshold` 必须 < 1.0**（官方 0.85）——tone mapping 在写后处理缓冲时就已应用，"
             "缓冲区里没有 >1 的值，写 1.15 永远不触发（这就是调 5 轮 bloom 毫无变化的原因）；"
             "灯在 legacy 模式下是美术值（内部 ×π），「4.5 W / 11 m」不是物理量，"
             "要物理就全局切 `intensity=cd` / `power=lm`；**Blender(Cycles) 的数值不能照搬到 three.js**。"
             "还有两个坑：①**`FogExp2` 的雾色不能比夜空亮**——`FogExp2(0x241428, 0.0085)` 在 100 m 处衰减因子 "
             "`exp(-(0.0085*100)^2)≈0.49`，远处楼一半染成雾色、整条街变「灰紫黄昏」；换 `(0x090b16, 0.0038)` "
             "立刻变深夜。**压暗天空球却没变化时，先查雾，不是继续调天空**（2026-11-10 白调一轮才找到）；"
             "②**自发光判定不能只看 `emissive > 0.02`**——会把墙 / 路缘 / 人行道全变成发光体（用户原话「白灰调的墙太亮」）；"
             "改用材质名白名单（本场景 `GLOW = /^(darkglass|shopinterior|warmlight2?|neonpink|neoncyan|neonyellow|neongreen|letter|signred|signorange|signgreen|vending)$/`），"
             "不在名单就 `m.emissive.setRGB(0,0,0); m.emissiveIntensity = 0`（实测清掉 8 个）",
             "改一个参数必须能看到画面变化——看不到就说明它没生效，先查机制再调值（不是继续试）；"
             "**画面暗/闷先怀疑构图，再怀疑灯**：2026-11-11 实测把相机从 3.30 m 俯视降到 1.75 m 人眼高度，"
             "观感提升比连调 5 轮灯光都明显——「路面占比太大把注意力吸走」不是亮度问题，"
             "相机高度改的是取景不是光照；同一天同一场景调灯的 5 轮里 4 轮无效"),
            ("J", "【关卡】夜景地面反光（金属度高反而更黑）",
             "湿沥青的霓虹倒影 = 招牌光打在路面上的镜面反射，**不是天空环境光**。"
             "成本近零的做法：加一层 additive 的竖条光带平面——canvas 画 30 条竖直渐变"
             "（霓虹色板 `#ff3d8b/#ffd479/#57e6ff/#8bffb0/#ff8a3d/#c77bff`，中间亮两头透明），"
             "`PlaneGeometry(size.x*1.02, size.z*1.02)` + `rotation.x=-Math.PI/2` + `y=0.02`，"
             "`MeshBasicMaterial{transparent, blending:AdditiveBlending, depthWrite:false, toneMapped:false}`",
             "**地面法线朝上 → 反射的是 env 的上半球（天空）；夜空本身是暗的，所以 metalness 越高越黑**"
             "（2026-11-11 调了 4 轮才找到）。三个无效尝试，别重复：①提高 `HemisphereLight`——照的是漫反射不是反射；"
             "②把 envMap 提亮（渐变 `#05070f→#2a1a24` 改 `#070a14→#4a2c36`、霓虹光斑 90→170 个）——只让天空变亮；"
             "③`metalness 0.55 / roughness 0.18`——越像金属越黑。④`emissiveIntensity 0.18→0.28` 收益递减"
             "（沥青贴图本身均值约 0.03，乘出来还是黑）。`Reflector` 最真但要多渲染一遍全场景，"
             "77k 顶点的场景就是 2 倍开销；「看得见就够」时假反射层性价比最高",
             "截图字节数当可见刻度（555,577→581,585→639,534→676,641，**只有最后一步 +5.8% 是质变**）；"
             "更硬的判据：**路面在无直射光的区域也要有颜色，不能是纯黑 RGB(0,0,0)**——直接读像素，别看感觉"),
            ("I", "【关卡】glTF 后处理体检（导出后、交付前）",
             "`gltf-transform inspect x.glb` 打印 mesh 数（draw call 上界）/ 顶点 / 材质 / 贴图字节，"
             "官方说明明确提到「has too many draw calls」；再用 `join`→`dedup`→`palette`→`optimize` 逐项降；"
             "**`grep -c TRIANGLES` 就是 mesh 数的直接读法**（每个 mesh 至少一次 draw call）",
             "**本机已装 4.5.1**（`npm i -g @gltf-transform/cli`；sharp 镜像只能走环境变量 "
             "`SHARP_BINARY_HOST`/`SHARP_LIBVIPS_BINARY_HOST`——`npm config set sharp_binary_host` 会报 "
             "`not a valid npm option`）；**2026-11-10 实测**：1544 mesh 的街景 GLB，`join` 用 **1.17 s** "
             "把 mesh 压到 **20 个**（≈使用中的材质数，不是 1）、体积 3.71→2.75 MB；"
             "`optimize --compress draco` 要解码器，`--texture-compress webp` 依赖 sharp",
             "`inspect` 前后两次跑：**mesh 数**与贴图字节都变小才算过；只看文件变小不算；"
             "**贴图文件体积 ≠ 显存占用**（实测 14.15 MB 的 4096² PNG 上卡要 89.48 MB，看 `gpuSize` 不看 `size`）"),
            ("A", "高层组件库（drei / Three.js examples/jsm）",
             "湿地面反射(MeshReflectorMaterial)、HDR 环境光(Environment)、接触阴影(ContactShadows)都是一行调用，默认值已调好",
             "要引 React+构建，或至少用 examples/jsm；默认风格不一定合口味",
             "看效果有没有出现：倒影、菲涅尔高光、贴地阴影，一眼可判"),
            ("B", "lab blender 建模 → GLB",
             "真圆、真倒角、真打光；GLB 能给任何引擎用；headless 可脚本化",
             "要写 Python；首渲编译 shader 约 46 秒、之后 4 秒；相机用 TRACK_TO 约束别手调欧拉角；"
             "**glTF 导出器不支持程序化节点**——带 noise 纹理的材质 baseColor 会静默导成纯白 (1,1,1)；"
             "**`--factory-startup` 下 `read_factory_settings(use_empty=True)` 不生效，默认 Cube 会挡在原点"
             "（2026-11-11 四轮全黑的真根因，必须手动 `bpy.data.objects.remove`）**；"
             "`world` 变量别指望在后面定义过——节点代码里用到就自建 "
             "`bpy.data.worlds.get('World') or bpy.data.worlds.new('World')`；"
             "**体积雾 `VolumeScatter` 密度 0.0075 会把远景全糊掉，0.0012 才对**",
             "有 GLB/PNG 产物，大小和像素可验——是数字不是感觉；"
             "`dump-mats.py` 逐条查 baseColor/emissive 有没有丢"),
            ("K", "Blender 程序化有机形状（骨架 + Skin Modifier）",
             "**树 / 血管 / 触手这类分叉结构，只给骨架顶点 + 每点半径，Skin Modifier 自动生成连续管、"
             "分叉自动融合**，零手写拓扑；配合 `SUBSURF(1)` 变圆。实测一棵树：1,306 骨架顶点 → "
             "110,268 顶点 / 110,360 面，树干从头到尾一根连续管、没有段接缝。三条配套手法："
             "①**根盘用 `r(h)=a+b*exp(-h/c)` 让基部外扩**（成年树没有土堆，根埋地下、地表只留浅脊）；"
             "②**树皮沟槽做进几何**——`sin(θ*N + noise(z))` 推顶点，贴图 bump 改不了逆光轮廓；"
             "③**叶片 alpha 贴图用 Python 逐像素画**（`img.pixels = px` + `img.pack()`），不依赖外部素材",
             "**`skin_radius` 不在 `mesh.vertices[i]` 上，在 `mesh.skin_vertices[0].data[i].radius`"
             "（Skin 层在加 modifier 后才存在，写错直接 AttributeError）**；`skin.branch_smoothing=0.35` 防分叉处扁片，"
             "分叉角控制在 0.45–0.85 rad（太小生成纸片）；**不要用 N 个 `primitive_plane_add` + `join` 建几千片叶子**"
             "——4,482 个对象 10 分钟被 `timeout 900` 杀掉，改 `bmesh` 一次生成秒过；"
             "**`Subsurface Radius` 单位是米**，对 0.3 m 的叶子给 `(0.05, 0.07, 0.02)` 会让整片黑掉；"
             "**双层卡片在 `CLIP` 模式下叠加会变暗 + 毫米级偏移产生重影**（想加厚度别用这招）；"
             "**改任一生长的『向上分量』会让树冠塌**——把 `lift 0.16→0.06` 实测 `tips 249→186`，"
             "因为外围枝不往上走 → 半径更快衰减到阈值 → 递归提前终止",
             "`skinned` 顶点数应是骨架的 50–100 倍（1,306 → 110k）；树干截图**逆光边缘是锯齿的**（沟槽在几何里）"
             "而不是光滑弧线；根看不见整条、只有基部外扩 + 地表浅脊；"
             "**改任何生长参数后要重新数 `tips`**（数掉一半就是塌了）；`STEP1d` 日志应打沟槽条数与深度"),
            ("L", "【关卡】网页 3D 性能预算（六条硬指标，交付前必过）",
             "**先把预算表立起来，再谈优化**——微缩 / diorama 题材在网页上跑 60fps 完全够用，六条硬指标："
             "①全场景三角面 ≤15 万 ②draw call ≤120 ③材质数 ≤20 ④纹理总大小 ≤4 MB "
             "⑤实时阴影只算一次（静态场景）⑥单个「道具级」物件 300–3000 面。"
             "**先量再改**：页面里挂 `window.__STATS__ = () => ({calls: renderer.info.render.calls, "
             "triangles: renderer.info.render.triangles, textures: renderer.info.memory.textures, "
             "geometries: renderer.info.memory.geometries, pixelRatio: renderer.getPixelRatio()})`，"
             "配 `renderer.info.autoReset = false` + 每帧 `renderer.info.reset()` + 缓存 `window.__CALLS__`，"
             "用 CDP 读真值再动手。定了表之后很多决策是自动的——比如「这棵树要不要 transmission」这种问题"
             "根本不用讨论，预算里没有它的位置",
             "**别信估算，信 `renderer.info`**——2026-11-11 一棵树实测 `calls 32`（31 个 mesh 有视锥剔除），"
             "远低于按「每个物件一个 draw call」估的 150–250；**真正决定开销的是「pass 数 × 三角面数」，不是单纯三角面数**——"
             "`renderer.info.render.triangles` 统计的是**本帧所有 pass 的累计提交量**（主 pass + 阴影 pass + transmission pass），"
             "实测 69.8 万 / 23.3 万 = 3.0、关阴影后 46.5 万 / 23.3 万 = 2.0，正好对上「3 pass → 2 pass」。"
             "**所以 transmission / SSAO / 描边 / bloom 这类「再加一遍场景」的东西，代价是成倍放大而不是线性的**，"
             "每加一个都要先算这笔账。三条已验有效的减法：①`renderer.shadowMap.autoUpdate = false` + "
             "模型加载完成后 `needsUpdate = true`（静态场景阴影只算一次）→ 三角面 69.8 万→46.5 万（-33%）、calls 49→32；"
             "②Blender `Decimate(COLLAPSE, ratio=0.12)` 把树 110,360 四边面→22,616 → "
             "**GLB 8.75 MB→1.64 MB、单文件 HTML 12.4 MB→2.9 MB，肉眼无差**；"
             "③去掉 `KHR_materials_transmission`（draw call 32→17，几乎减半，它不只是多渲一遍、还多一组 pass）。"
             "**别做的**：`KHR_materials_transmission` 会让 three.js **每帧多渲一遍整个场景**，"
             "只为一点透光不值得；`setPixelRatio(Math.min(dpr, 2))` 在高 DPI 屏等于像素量 ×4，降到 1.5 肉眼无差。"
             "**口径必须说清**：说「某物件占 x%」时要说清是「全帧累计提交量」还是「主 pass 内可见几何」——"
             "同一棵树按全帧算 31.6%、按主 pass 内算 95%，两个数都对但意思完全不同，写错会误导后续判断",
             "`window.__STATS__()` 的 `triangles ≤ 150000` 且 `calls ≤ 120`，**外加两条新指标**："
             "**①pass 数 ≤ 1**（不加任何后处理时）—— 算法：`renderer.info.render.triangles / 主 pass 实际几何三角面`，约等于 pass 数；"
             "或查材质里有没有 `transmission` / 自定义 `RenderPass`；"
             "**②overdraw 面积 ≤ 屏幕 30%**——透明叠加物（additive 反射条、光晕面、玻璃、雨、花瓣）是像素级重复填充，"
             "量法：Chrome DevTools → Rendering → Paint flashing 看红块覆盖率，或临时把全部透明物 hide 对比帧率。"
             "**测量时机是关键**——`window.__READY__` 只是模型加载完，渲染稳态还要等 1 秒，"
             "否则读到第一帧 `calls:1 / tris:72` 的假值（已踩）；"
             "**文件体积**（GLB / 单文件 HTML）也要记进交付说明，它是下载时长和内存的直接来源"),
            ("C", "下 CC0 低模 + GLTFLoader",
             "细节上限最高（细辐条、立体字、树）",
             "风格会打架，得挑同一个包；变成 HTML + 十几个 GLB",
             "能跑起来就算过，但『像不像同一个世界』只能靠看"),
            ("D", "Three.js 手写坐标（垫底）",
             "零依赖、单文件、完全可控、风格统一",
             "一个湿地面反射要自己搭 render target；11-06 实测 28 分钟只够做到薄壳盒子那版；"
             "11-10 实测 8 小时出的成品被用户判「只是大体形状」",
             "截图对元素清单；没有退出码"),
            ("M", "建模前先推理物体（轮廓 / 比例 / 部件 / 连接 / 表面身份）",
             "来自 3dviz-pro-max（`viettranx/3dviz-pro-max`，1,255★，MIT）的 7 步工作流第 2 步："
             "选模板之前先说出这个物体六件事——**轮廓**（只看剪影能不能认出来）、**比例**（各部分相对尺寸）、"
             "**部件**（由几块组成）、**连接**（连续皮 / 分层覆盖 / 分离铰接）、**表面身份**"
             "（混凝土/瓷砖/金属/布，决定材质与纹理尺度）、**行为**（静态/可动/受什么约束）。"
             "**先解最难或最有辨识度的那个物体**，别先把容易的堆满、最后发现主角做不出来",
             "是**判断**不是产出，单独写不出几何；推理完仍要走 B/D 的构造路径；"
             "它治的是「做出来像一坨」，不治 draw call（那看 F/L）",
             "能对着成品逐条回答这六个属性、并指出参考图对应哪几处；"
             "而不是「我觉得做得还行」"),
            ("N", "做 3D 前先查有没有现成配方（别从零想）",
             "`skill({name:\"3dviz-pro-max\"})` 加载后，`cd C:\\\\Users\\\\<user>\\\\.dsh\\\\skills\\\\3dviz-pro-max && "
             "python scripts/search.py \"<主体+未决问题>\"` 得到 BM25 排序，再 `resolve.py <record-id>` 取完整记录。"
             "223 个 recipe + 440 条 knowledge 覆盖科学可视化（心动周期瓣膜 / 臂丛神经路径 / 毛细血管交换 / 浮力平衡）、"
             "工程（桥的载荷路径 / 拆装顺序 / 可达性间隙）、算法（二进制堆 / BFS 前沿 / DAG 拓扑序）、产品与街景。"
             "**每条 recipe 都带 `invariants`（不变量）、`known_limits`（作者自述哪里没把握）、"
             "`claims`（带 source_refs.locator 出处）、`state_contract`（谁是权威状态）**",
             "配方是**候选不是指令**（SKILL.md 原话「candidates to adapt, not instructions to copy every value」），"
             "照抄数值会得到「正确但平庸」；正文全英文；只覆盖它收录的 223 个主题，没收录的仍要自己推理；"
             "`capture.py` 需要 node + playwright，本机尚未验证能不能跑",
             "能说出用的是哪条 record（`recipe.xxx` / `knowledge.xxx/yyy`）、改了它哪几个 `defaults`、"
             "以及它的 `known_limits` 里哪一条在本次交付里成立"),
            ("O", "动效 / 交互场景先写状态契约（谁是权威、谁是派生）",
             "3dviz-pro-max 的 `state_contract` 做法：先定唯一权威状态（如「相位索引」），"
             "其余全是派生（瓣叶姿态 = f(相位)、腔室体积 = f(相位)），再定一条不变量「往回拖必须精确还原之前的姿态」。"
             "映射到 three.js：**一个状态对象持有全部可变量，mesh 的 position/rotation 每次从它算出来**，"
             "不要在多处分别 mutate mesh；动作只改权威状态，不改派生量",
             "只对「有状态切换」的场景必要（动画、分步演示、可拖拽时间轴）；纯静态场景是过度设计；"
             "状态分支多到画不出来时，先拆成两条独立状态机，别硬塞进一个",
             "能对着代码指出「权威状态在哪一行」「哪些量是派生的」；"
             "往回拖 N 步后数值逐位还原（不是「看起来差不多」）"),
        ],
    },
    {
        "domain": "视觉 / 界面 / 截图验收",
        "words": ("截图", "界面", "预览", "视觉", "好看", "配色", "布局", "UI", "样式",
                  "动画", "入场", "过渡", "进度"),
        "routes": [
            ("A", "写 verify.mjs 式验收器（契约钩子 + headless + 数字表）",
             "一次跑完出 6 个 PASS/FAIL，15 秒拿到数字；骨架可改造成任何视觉交付",
             "要先在页面里写死 window.__X__ 钩子；抽查的是写死的指标不是美不美",
             "退出码 0=全过 / 1=有失败 / 2=脚本自身错误"),
            ("B", "lab cdp 连已开浏览器截图/执行 JS",
             "能读运行时状态、能点元素；不依赖页面 hook",
             "只能截当前一帧；要自己先开好页面；路径是位置参数不是 --out",
             "截出来的 PNG 能打开、能看清内容"),
            ("C", "lab desktop 截屏 + 模拟输入",
             "连桌面程序也能验（不是网页）",
             "坐标是逻辑像素 1707x960，点错会误开窗口；默认 dry-run 要 --yes；只点能撤回来的",
             "点完立即截屏确认目标状态变了"),
            ("D", "read_image 我亲眼看",
             "能判断构图、色彩、层次这些指标写不出来的东西",
             "一次只能看一张；容易陷进调参数循环（11-06 实测 18 轮里 14 轮在调参）",
             "先定「看什么」，看完就停，不追完美"),
            ("E", "先把状态收成一个 0~1 的数（progress）",
             "所有视觉派生量都从它算（断几座桥=floor(p*26)、倾斜=swing*p、亮度=p）；"
             "验证器只读一个数，不用采样+插值；配 seededRandom 连随机感都稳定",
             "要先改页面结构；多轴独立运动得拆成几个数；不是所有视觉效果都能压成一个数",
             "document.querySelector('[data-progress]').dataset.progress 一个数能复原整个画面状态"),
        ],
    },
    {
        "domain": "图片 / OCR / 看图理解",
        "words": ("图片", "OCR", "识图", "照片", "图里", "看这张", "截图里"),
        "routes": [
            ("A", "lab ocr（RapidOCR 本地）",
             "免费、0.6 秒、离线；只要文字时最划算",
             "只提字不理解内容；版面复杂会乱序",
             "置信度 ≥0.9 才信，低于 0.6 当作没识别到"),
            ("B", "vision_describe（GLM-4V 优先，本地 vl 兜底）",
             "能回答问题、能描述画面；自动降级不中断",
             "小图标/小字会看错（11-05 把任务栏图标当成桌面图标）",
             "关键结论再用 read_image 复核一次"),
            ("C", "read_image 直看",
             "最准，没有任何中间层",
             "一次只能一张，要我人在",
             "看完能说出具体位置和数量"),
        ],
    },
    {
        "domain": "AI 生图 / 视觉素材生成",
        "words": ("生图", "生成图", "生成一张", "出一张", "做一张", "出图", "参考图",
                  "配图", "插图", "封面", "海报", "示意图",
                  "概念图", "素材图", "AI画", "画一张"),
        "routes": [
            ("A", "tools/aigen/gen.mjs（智谱 cogview-3-flash）",
             "8 秒出 1024×1024；中英提示词都能用；单图交付/概念图/参考图的最快路",
             "按次计费；右下角带「AI生成」水印；**写不准文字**（招牌、标题、数字必错）；"
             "不能精确控制构图与视角；提示词写得越具体越像，但改一次要重出一张",
             "① 看图确认没有畸变/多指/文字乱码；② 需要准确文字时**不要**用 AI 生图，"
             "改用程序化画或后期贴字；③ 记下模型名和提示词，换模型会换风格"),
            ("B", "程序化绘制（PIL / matplotlib / canvas）",
             "数字和文字绝对准确、可复现、免费；图表/示意图/线框的最优解",
             "只能画几何与图表，画不出照片级；复杂构图代码量大",
             "数值逐项核对、图上文字与实际数据一致"),
            ("C", "找现成图（Wikimedia / Unsplash / 官方素材库）",
             "真实照片、可信度高；官方图通常授权清晰",
             "**本机实测多数源被封**：Wikimedia 超时、Unsplash `napi` 401、"
             "百度图片 `antiFlag`、Bing HTML 只出 1–2 条 murl；能拿到的多为低分辨率或版权不明",
             "记录来源 URL + 授权协议；分辨率够不够用"),
            ("D", "截屏 / 录屏（lab cdp / lab desktop）",
             "真实界面或真实窗口，零生成成本，所见即所得",
             "只能反映已经存在的东西，做不出新画面",
             "截图里目标元素确实出现，不是「差不多」"),
        ],
    },
    {
        "domain": "排查 / 长日志归因",
        "words": ("报错", "日志", "排查", "归因", "为什么", "挂了", "失败", "异常"),
        "routes": [
            ("A", "tools/edge-lab/triage.py（本地 3b 先筛）",
             "几百行日志先让它挑候选行，我只裁决候选；实测 8/8、精确率 0.94",
             "只认硬证据(ERROR/FAILED/MiB/assert)；>150 行自动切 coder；跨语义判断不了",
             "候选行数应远小于总行数；精确率靠 truth.json 回归"),
            ("B", "lab errors（报错原文按工具聚合）",
             "只列原文和频次，不给建议——先看清形状再动手",
             "不带上下文，长报错会截断",
             "同类报错频次排第一的那个就是入口"),
            ("C", "lab sessions / session_search 找以前的同类现场",
             "可能已经踩过并修过；比从零推理快",
             "字面匹配不语义（搜「插件迭代」0 条、搜「dsh-ops」4 条）",
             "找到的会话要用 session_trace 确认是同一个问题"),
            ("D", "lab lsp 查定义/引用",
             "定位符号比 grep 准，能跨文件",
             "要 pyright；只支持 Python",
             "hover 能出类型、refs 能列全调用点"),
            ("E", "从 DSH 自己的 session 文件数事件，不靠反推",
             "路径 `~/.dsh/sessions/--<编码后的 cwd>--/session-*/session.v4.jsonl.zstd`（zstd 压缩，"
             "runtime python 有 zstandard 库）；解压后逐行 JSON，按 event.type 计数、按 turn/step 分组，"
             "就能给出「谁在什么时候产生了多少条什么事件」的硬数字。2026-11-11 用它查出 234 条 "
             "system/message、每条 45,463 字符，直接推翻了从 bili 逻辑反推的结论",
             "目录名是 cwd 的路径编码（`E:\\DS公作区` → `--E-DS~516C~4F5C~533A--`），不是明文；"
             "`session_event_search` 可能报 `session history storage is unavailable`，别把它当唯一入口；"
             "只读不写，会话进行中别改它",
             "能给出四元组：事件类型 → 条数 → 每条字符数 → 是否按 step 递增；而不是「我推测」"),
        ],
    },
    {
        "domain": "推理档位 / 思考深度",
        "words": ("推理档位", "降档", "升档", "思考深度", "想得浅", "这么浅", "reasoning", "thinking level", "草率"),
        "routes": [
            ("A", "查实际生效的 reasoningEffort，不靠感觉",
             "每轮请求的 `reasoningEffort` 值写在 session 文件的 `request/header` 的 `config.reasoningEffort` 里"
             "（读法同「排查」域 E 路线）。同一个 turn 内的不同 step 可以取不同值"
             "（2026-11-11 实测 `seq 6352 turn 59 step 1 = low`、`seq 6359 step 2 = high`）",
             "`reasoningEffort` 是**请求参数**，不是「我实际想了多深」的证明；低档位不等于答错，只是推理预算小；"
             "不同模型对 `low`/`medium`/`high` 的映射不同，看到 null 先查这个模型认不认这个字段",
             "能报出四元组：turn/step → provider/model → reasoningEffort → 这轮干了什么；"
             "而不是「我觉得这轮想得挺多的」"),
            ("B", "切档位的代价：prompt cache 重新分区",
             "档位在两步之间变化时，上游会把 prompt cache 重新分区，那段前缀要重算。"
             "`acp_cache` 的 `EFFORT SWITCHES` 一栏直接给次数与总重计费；2026-11-11 实测冷切 225.5K、"
             "暖切 29.3K（bili 注释 #3803）",
             "代价是**缓存重计费**，不是推理质量；切换少的时候可以忽略，切换频繁就变成主要 miss 来源",
             "按天看 `EFFORT SWITCHES` 的次数与总重计费，只在高频时才有优化价值"),
        ],
    },
    {
        "domain": "改插件 / 部署 / 装东西",
        "words": ("插件", "deploy", "安装", "卸载", "profile", "cordis", "bundle", "升级", "市场", "社区", "dshmarket", "mcp", "skill", "技能", "插件索引", "现成的", "第三方", "cli", "命令行工具", "可执行文件"),
        "routes": [
            ("A", "lab deploy <包名>（改完自研插件同步到 profile）",
             "软链自动跳过、实体拷贝自动备份；改完就知道有没有同步",
             "只对 SELF_BUILT 表里的 10 个包有效；SKILL.md 热读不用重启，代码要重启",
             "lab deploy --all --check 输出 0 差异"),
            ("B", "lab vet（装之前扫代码）",
             "8 条规则查 proc/eval/secret/postinstall/b64/net/fs-write/env",
             "只扫静态代码，看不出运行时行为",
             "HIGH 命中必须人工过一遍再装"),
            ("C", "手改 cordis.patch.yml + 复制 node_modules + 重启",
             "能装任何东西，不受 install_bundle 的版本号限制",
             "DSH desktop 被 Electron 独占；改前必须备份",
             "重启后 lab plugins 能看到、工具真能调"),
            ("D", "lab plugins（查现状）",
             "一眼看全 bundle 的版本/客户端/描述",
             "只读——告诉你装了什么，不告诉你该不该动。且 installed/source 是从 dependencies 推的，"
             "bundles 里有而 dependencies 没有的会显示 installed:false（2026-11-05 栽过）",
             "版本号和 package.json 对得上"),
            ("E", "env_doctor only=health（验能不能真加载）",
             "能加载 ≠ 工具发布；它抓 import 层面",
             "抓不到「加载了但工具没注册」（11-05 dsh-ops 就是）",
             "再看工具表里有没有对应工具"),
            ("F", 'plugin_manager list_bundles / list_plugins（官方视角）',
                '比 `lab plugins` 更全：能看到 fiberPhase、installed、source、readOnlyReason——**判断「到底加载了没」看 fiberPhase 不看配置文件**',
                '只读列表要分页（total 250+）；装/卸会触发 pnpm 重算，有风险',
                '目标插件的 fiberPhase 是 "active" 且 enabled 是 true'),
            (
                "H",
                "dsh-community / dshmarket（插件市场 / 社区安装通道）",
                "装之前先看有没有现成的，别自己造；dshmarket 是可视化市场，dsh-community 是目录与安装通道",
                "两者都只是入口，装完仍要走 lab vet + env_doctor only=health 验；市场里的插件不是「装了就对我好用」",
                "装完跑 env_doctor only=health 看它真能加载、plugin_manager list_plugins 看 fiberPhase 是 active",
            ),
            ("G", 'cordis_inspect_query（读运行时真实定义）',
                '能读到 Service 方法签名、Config schema、Tool 的完整定义——**「包里有定义」和「运行时发布了」是两件事，这个工具看的是后者**',
                '只读；Config 的 status:"absent" 只表示没有 config schema，不代表插件没加载',
                '能查到某个工具的真实参数 schema（而不是猜）'),
            ("I", "改 system prompt 注入前先查缓存签名",
             "凡是要进 system prompt 的动态内容（时钟、记忆注入、tool hint、压缩段），必须参与插件的"
             "签名/缓存判等，否则每一处变化都变成一次全量重计费。2026-11-11 实测：dsh-memory 的 "
             "readClockLine 拼在 injectionCache 外面（分钟级），累计 27 次 prompt rewrite / 4.18M tok",
             "要读插件源码找 injectionSignature/缓存判等函数，不能只看「它显示出来了」",
             "改完跑 acp_cache 看 PROMPT SWITCHES 没有新增；或连调两次 renderInjection 比对输出字节"),
            ("J", "改配置字段前先查门禁：offer vs withhold",
             "字段能不能在 profile 里写，不取决于 schema 允不允许，取决于该协议在 `COMPAT_GATES` 里是 "
             "`offer` 还是 `withhold`——`compatProtocols(field)` 只返回 offer 的协议。"
             "2026-11-11 实例：想给 qwen-plus 加 `compat: {supportsMidConvoSystemMessages: false}`，"
             "但 `openai-completions` 对该字段是 withhold，写了会被 `assertOfferedCompatFields` 拒绝",
             "`withhold` 的字段写了会被拒绝报错（不是静默忽略）；运行时值可能来自 registry 内置，"
             "profile 无法覆盖 → 这种只能报上游或换方案，别反复改配置试",
             "能说出「这个字段在哪个协议下是 offer / 哪个是 withhold」+ 有无配置层开关；说不出来就别改"),
            ("K", "把外部 CLI 接成 DSH 的 MCP 服务",
             "四步：①`<cli> mcp --help` 先确认传输是 stdio 还是 http；②手工灌 "
             "`initialize` + `notifications/initialized` + `tools/list` 验握手、数出工具个数；"
             "③建配置-only bundle（`package.json` 只需 name/version/`dsh.bundle.patch`，"
             "`cordis.patch.yml` 写 `- insert: - id: <x> / name: '@deepseek-ai/dsh-mcp-client' / "
             "config: {serverName, transport: stdio, command, args, failOnStartupError: true}`，"
             "stdio 的 command 要指**真实二进制**不是 .cmd wrapper）；④`plugin_manager install_bundle` "
             "后调 `mcp__<serverName>__<tool>` 验。2026-11-12 实例：agent-desktop → serverName `desk`、67 工具",
             "`application: applied` 就即时生效，**不用重启**（env_doctor 那条「配置已改动可能没重启」是时间戳误报）；"
             "serverName 决定工具前缀，改名等于所有调用点失效；bundle 必须放工作区，不要手写 profile 的 package.json",
             "`mcp__<server>__<某个只读命令>` 返回 ok:true 且数据是真的（不能只有 status 能通）；"
             "工具表里能看到全部工具"),
            ("L", "缺能力时先查插件索引，别自己想",
             "`E:\\DS公作区\\插件库\\awesome-index.json`（5,437 条，字段 name/title/description{en,zh}/"
             "metadata.category/repository.url）先搜一遍：有现成的先 `lab vet` 再装，没有才自己写。"
             "2026-11-12 起这是常规路径——旧的「批量下载 4,000+ 插件逐个读」已废弃（5.7 GB 已删，只留索引）",
             "索引是第三方文本，**在列表里 ≠ 安全审查**，装之前必须 `lab vet`；远程源（jsdelivr/unpkg）拉 4.4 MB "
             "会超时，刷新走 npmmirror CDN 的 tarball 快路径",
             "能说出「查了哪些关键词、命中哪几个、选 X 不选 Y 的理由」；说不出就是没查"),
            ("M", "把外部 Agent skill 装成 DSH skill",
             "DSH skill = 一个目录 + `SKILL.md`（frontmatter 有 name/description）+ 引用文件，"
             "放到 `C:\\Users\\<user>\\.dsh\\skills\\<slug>\\` 就自动出现在技能目录，**不用注册**。"
             "Claude Code / Codex 的 skill 结构基本兼容，通常只需改 frontmatter。"
             "2026-11-12 实例：3dviz-pro-max 746 文件 / 6.3 MB 直接可用",
             "别整包搬：`.claude-plugin` / `.codex-plugin` / `agents/*.yaml` 是别家插件壳，DSH 用不上；"
             "`templates/` 若是脚手架也常可省。**scripts 不是模型**，是可选的查表/验收工具，去掉不影响方法论",
             "`skill <name>` 能加载，或系统提示的技能目录里出现该名字；"
             "本机网络拿 GitHub 仓库要走 `gh api <path> -H \"Accept: application/vnd.github.raw\"` 逐文件"),
            ("N", "把自研插件补到可发布（2026-11-13 三个包实测）",
             "发布前清单：①名字——`@local/` 是本地占位 scope，**发不到公共 npm**，要么改成真 scope（如 `@un10086/`）要么用裸名；"
             "②`\"private\": true` 会直接阻止 publish，必须删；③补 `LICENSE` 文件（MIT 全文，`Copyright (c) 2026 <作者>`）+ `license` 字段；"
             "④补 `author`/`repository`/`bugs`/`homepage`/`engines`；⑤写 README（装法 + 凭据怎么配 + 什么时候别用）；"
             "⑥**去硬编码**：把工作区根目录这类绝对路径改成 `process.env.DSH_WORKSPACE || \"默认值\"`；"
             "⑦`npm pack --dry-run` 看文件清单，`.bak`/`test.*` 会被漏掉",
             "三个坑：①**删 `private` 之后 profile 也能被 publish 影响**，发布前先确认 profile 里关联的 bundle 名同步改了，否则本地插件会报「找不到」；"
             "②改 scope 要连着改三处（`package.json` 的 name、`cordis.patch.yml` 的 name、profile `package.json` 的 bundles/dependencies），少一处就是运行时找不到；"
             "③**批量替换路径时替换串必须保留原有分隔符**——`join(\"<绝对路径>\", ...)` 改成 `join(WORKSPACE_DIR\", ...)` 会丢逗号报 `missing ) after argument list`",
             "`npm pack --dry-run` 输出的文件数/体积和预期一致（无 `.bak`、无 `test.*`），且 `node --check` 通过、本地装上后工具真能调"),
            ("O", "改包名/scope 后，客户端注册 id 必须逐字等于 package.json 的 name（2026-11-13 崩溃根因）",
             "client-modules 的 graph row id 取**包名**、不是 patch 的 entry id（node 半 `lib/index.js:957` "
             "`graphRow(packageName,…)`）；浏览器半 `arrive(row)` 跑完 batch 若 `factories` 里没有 `row.id`，"
             "就回落该包单资源 URL **再执行一遍同一份 client.js** → `duplicate factory registration` "
             "→ web boot `1 entry did not activate`，界面直接打不开、只能禁用所有插件才进得来",
             "要改的名字有四处（`package.json` name / `lib/client.js` 的 `__ModuleLoader__.load({id})` / "
             "`cordis.patch.yml` 的 name / profile 的 bundles+dependencies）；**热加载看不出来**——"
             "只有冷启动才走这条路径，所以「没报错」不等于改对了",
             "①`node --check` + js-yaml 解析 patch（`@` 开头的值必须带引号）；"
             "②离线复现 `E:\\DS公作区\\.tmp\\sim_boot.mjs`（真实 client-modules + 真实 client.js，旧 id 必抛 "
             "duplicate、新 id `executed=1`）；③`env_doctor only=bundles`（2026-11-13 起连「装在 "
             "dependencies 但没启用」的包也查，报 WARN「启用即崩」）；④真验收=重启一次看界面能不能开"),
            ("P", "profile「整体重写」会静默删掉手写 patch 段（provider/千问消失就查这个）",
             "DSH desktop 的 profile 编辑/安装动作会**整块重写** `cordis.patch.yml`：不在它管理范围内的"
             "手写 `- insert:` 段直接消失，不报错、不提示。2026-11-13 实例：`llm-pi-ai` 的百炼 provider 段"
             "被 14:42 那次重写删掉，模型选择器里 qwen 全没了——**看起来像模型下架，其实是配置被吃掉**",
             "只能事后比对；每改一次 profile 相关配置都可能再来一次",
             "`ls -la ~/.dsh/profiles/desktop/cordis.patch.yml*` 看有没有新 `.bak-*`，再 diff 当前文件与最近备份，"
             "确认手写段还在；判据=配置里的 entry 条数与上次一致、`node -e` 用 js-yaml 解析出的 entry id 集合没少"),
            ("Q", "第三方插件自带 CLI：状态页说 available ≠ 能 spawn（2026-11-13 agentero 实测）",
             "①读插件源码确认它 spawn 的到底是哪个字符串（`runAgentero(settings.agenteroBin)` 的默认值就是裸 `agentero`，**不会**回落到它自己识别到的 managed 二进制——`source: managed` 只用于状态页显示）；②把可执行文件放进**本来就已在宿主 PATH 里**的目录（本机 `C:\\Users\\<user>\\.local\\bin`），立刻生效、不用重启；③验证要直接调那个工具，不看状态页",
             "改注册表 PATH 对运行中的宿主进程无效（env 在启动那一刻固化）；拷一份 exe 会多占磁盘（agentero 33 MB）",
             "调一次该工具（如 `agentero_list_papers`）返正常 JSON 才算通；available/version 只算旁证"),
        ],
    },
    {
        "domain": "写代码 / 改代码",
        "words": ("写代码", "改代码", "实现", "重构", "函数", "脚本", "修 bug",
                  "新特性", "加特性", "补丁", "旧代码", "遗留", "赋值", "循环条件", "while"),
        "routes": [
            ("A", "edit 工具直接改（小改）",
             "最快；带版本校验，改前必须 read 过",
             "大改会撞 FS_STALE_VERSION；UTF-8 文件绝不能用 PowerShell 管道改；"
             "**`ops_replace` 对多行含中文注释的代码块会返回 `changed=0 matched=0`**（2026-11-10 连试两次都不中，"
             "缩进、换行符都逐字确认过）→ 改长 JS / 长中文块一律用 `edit` + **单行锚点**，不要用整段 literal 去匹配",
             "改完 node --check / py -m py_compile / 跑一次"),
            ("B", "lab lsp 先查清楚再改",
             "知道谁在调它、类型对不对，避免改出隐式破坏",
             "要 pyright；慢几秒",
             "refs 列全了才动手"),
            ("C", "lab snapshot 先存一份",
             "改坏能退；比 git 轻",
             "只存文件副本，不存语义",
             "snapshot list 能看到刚才那份"),
            ("D", "tests/ 里的现成测试",
             "有回归就有判据；比肉眼可靠",
             "老测试可能本身写错了（断言凭印象数）",
             "pytest 退出码 0 且新增用例覆盖这次的 bug"),
            ("E", 'ops_grep + ops_glob 先定位「这个函数/字段还有谁在用」',
                '改之前先知道影响面——2026-11-07 的教训是「改 A 忘了 B」，一次搜索能省一轮返工；ops_glob 的 pattern 是数组，ops_grep 支持 before/afterContext',
                'ops_glob 的 `*.md` 只匹配顶层，要用 `**/*.md`；跳过 .git 和隐藏文件',
                '搜索结果的匹配数能和 `git grep -c` 对上'),
            ("F", 'ops_read_files 一次读多个文件（独立 range）',
                '批量读 3-5 个相关文件比逐个 read 快，且每个文件独立 offset/limit、互不干扰',
                '总行数有上限，超大文件要分页；不是所有工具都能替代它',
                '一次调用返回多个文件、每个都带行号'),
            ("G", 'ops_inspect_local_file 读单个文件的精确行范围',
                '只需要看第 120-160 行时不用整文件读，返回带行号',
                '只读不写；目录会被拒（要先 ops_glob）',
                'offset/limit 边界正确，文件尾不会越界'),
            ("H", 'ops_bash（跑命令 / 构建 / git / 管道）',
                '本会话唯一能跑命令的通道；脚本、构建、git 操作全靠它。长任务设 run_in_background 拿 jobId，不用干等',
                'Windows 上 `py` 是 .cmd，bash 里要写完整路径 `"/c/Users/<user>/.local/bin/py.cmd"`；stdout 可能被截断到 spill 文件；'
                '**Windows 路径必须写正斜杠**——bash 里传带反斜杠的 Windows 路径（`...\\.tmp\\x.py` 这种）时，'
                '路径里的 `\\t` 会被当成 TAB 吃掉，报 `can\'t open file`（2026-11-10 实测踩到），统一改用正斜杠形式（`.../.tmp/x.py`）',
                'exit code 和 stdout 都能读到，失败时有 failure.code'),
            ("I", "加新特性前，先搜有没有「为旧前提写的补丁」",
                "一条 grep 就能找到——`FIX_` / `*_FIX` / 硬编码数值表 / `if (nm === 'xxx')` 这类名字；"
                "找到就先问「它的前提还成立吗」，不成立就让它跟新特性一起失效（或加守卫条件）",
                "**旧补丁不会自己失效，它会静默与新东西相乘**。2026-11-11 实测：three.js 端一张 `FIX_BASE` 表"
                "（为「没贴图、baseColor 导成白」那一版写的）把 `m.color` 设成 0.225，而 `m.color` 是贴图的乘数 → "
                "0.23×0.225≈0.05 直接把墙涂黑；排查了 4 轮才确认不是灯的问题。同型坑："
                "**「资源进了文件」≠「画面上看得见」**——inspect/stat 只证明数据层，视觉层只能截图证明",
                "改完必须看**输出/画面里有没有变化**，不能只看代码改了；"
                "判据：新特性生效前后，肉眼 / 像素 / 数字三者至少有一个能测出差异"),
            ("J", "`while ((x = f()))` 当循环条件：退出时 x 被赋成假值，后面再用就是空",
             "2026-11-13 实测：`let hop; while ((hop = map.get(name))) name = hop.to;` 之后"
             "`if (hop)` 永远不成立，警告一次都没打——逻辑看着对，最后一步被循环条件吃掉",
             "改成 for(;;) + break 多两行；只要循环体要保留「最后一次取值」，就别把赋值塞进条件",
             "写一条用例专门验「最后一次真实取值有没有被用上」，而不是只验循环跑了几次"),
        ],
    },
    {
        "domain": "测试 / 回归 / 交付验收",
        "words": ("测试", "验收", "回归", "交付", "做完了", "验证", "没改坏", "差分", "等价性", "证明正确"),
        "routes": [
            ("A", "pytest / node --test（有退出码的）",
             "唯一能当裁决者的东西；绿了就是绿了",
             "只覆盖写到的用例；「118 项全绿界面还是错的」发生过",
             "退出码 0 + 新增回归用例"),
            ("B", "verify.mjs 式独立验收器（视觉交付）",
             "不依赖我的判断，输出数字表",
             "要另写一个文件；指标写死了才能跑",
             "6 个 PASS/FAIL 全过且退出码 0"),
            ("C", "lab claims（我的话有没有证据接住）",
             "专治「说做完了其实没做」；54 条人工标注 94.4%",
             "只查断言形态，判断不了质量",
             "证据率 >70% 才算过关"),
            ("D", "lab fact（数字/路径/版本/行号逐个核）",
             "防编造；能查 git 里的短 sha",
             "中文数字是提示级不计分",
             "所有数字都绿或已标注来源"),
            ("E", "lab selfcheck（机制文档 vs 磁盘）",
             "文档里的计数/路径/子命令跟实际对不对得上",
             "只管文档一致性",
             "0 处漂移"),
            ("F", "lab test（跑 lab 自己的测试，带 --basetemp 不污染工作区）",
             "改完 lab.py 立刻能验回归；mutation check 证明测试不是假绿",
             "只覆盖已写的用例；新增子命令没测试它发现不了",
             "`lab test` 全绿 + 回滚任一修复对应测试变红"),
            ("G", "差分测试：同一套用例跑两个实现，比行为不比结构",
             "重写 / 移植 / 换依赖时唯一能证明「没改坏」的东西；判据来自原实现，不是我的想象；"
             "2026-11-13 实证：同一批边界用例先用自己实现跑 6/6 全绿，改写成差分立刻挂 1 条——自测只证自洽，差分才证一致",
             "要能同时跑两个实现（可 import 或可子进程调）；只覆盖用例写到的行为；"
             "**两边的场景对象必须每次新建（工厂函数）**——我第一次把副作用数组放在共享对象上，上游的钩子调用串进了我的实现，表现为「我这边一次都没调」；"
             "`deepEqual` 比 Blob / 流实例会挂，退化成比类型",
             "先证明测试不是假绿：故意改坏一处必挂——hookable 那次 13/13，改坏 1 处变 12/13"),
        ],
    },
    {
        "domain": "写文档 / 报告 / 笔记",
        "words": ("文档", "报告", "笔记", "写一篇", "总结", "整理", "说明",
                  "决策日志", "记日志", "记录", "复盘",
                 "架构图", "流程图", "时序图", "画个图", "图表",
                 # 2026-11-08 加：时间表述也属于「写出来的那句话准不准」
                 "时间", "早上", "下午", "晚上", "昨天", "前天", "上周", "上个月", "多久"),
        "routes": [
            ("A", "office 技能（docx/xlsx/pptx/pdf）",
             "真 Office 文件，能校验能渲染",
             "重；简单文本不值得",
             "生成后回读一次内容"),
            ("B", "知识库 append-note（tools/append-note.mjs）",
             "踩过的坑沉淀下来，下次能搜",
             "只适合短条目",
             "INDEX.md 里能查到"),
            ("C", "兴趣/故事目录（写到文件）",
             "长文、有观点、能回看",
             "不是任务产出，是自选；不追篇数",
             "写完自己读一遍，删掉废话"),
            (
                "E",
                "archify 技能（架构图 / 流程图 / 时序图 —— 可交互 HTML，可导 PNG）",
                "结构关系类的东西画出来比写出来清楚；这是唯一能把「谁调谁、什么顺序」画成图的现成能力",
                "要先有真实代码/结构证据（凭想画出来的图会骗自己）；改配色要写覆盖",
                "载入后产出 HTML 能打开，图上每个框都能对回源码里一个真实文件/函数",
            ),
            ("D", "lab lint（排版自检）",
             "小标题过长/一行多事实/长段落/超长行",
             "只提示不阻断",
             "无 WARN 或已确认可忽略"),
            ("F", "说任何时间词之前，先指出它的出处",
             "错的不是「不知道多久」，是「编了一个具体时段」——「早上 / 昨天 / 上周」看起来精确，"
             "比「刚才 / 之前」危险得多；四个可查看处：会话消息的 time 属性 / `date` / `lab since <日期>` / git log",
             "每句话都要多看一眼时间戳，慢一点",
             "说出的每个时段名都能指到上面四个出处之一；指不到就改写成「刚才 / 上一轮 / 之前」"),
        ],
    },
    {
        "domain": "做 PPT / 演示文稿",
        "words": ("PPT", "ppt", "幻灯片", "演示文稿", "汇报材料", "答辩", "路演",
                  "课件", "版式", "母版", "讲稿", "备注页", "deck", "pptx"),
        "routes": [
            ("A", "python-pptx 原生对象：形状/文本框/表格/图表，逐元素可编辑",
             "python-pptx 1.0.2 就在 DSH runtime 里，不用另装："
             "`C:\\Users\\<user>\\.dsh\\dsh-runtimes\\dsh-plugin-desktop-primary-runtime\\dependencies\\python\\python.exe`。"
             "只产出原生对象，不产图片——用户要能在 WPS 里选中改字、双击改数据。",
             "两条硬边界：①**母版不能加形状**，`prs.slide_masters[0].shapes` 是 `MasterShapes`，"
             "只有 `clone_placeholder/element/parent/part/ph_basename/turbo_add_enabled`，调 `add_textbox` 直接 "
             "`AttributeError`——页脚页码只能每页加；②**动画没有 API**，只有 `pptx/oxml/slide.py:165` 的 "
             "`timing = ZeroOrOne(\"p:timing\")` 和 `:197 add_childTnLst()`（本来给视频用），要做动画得手拼 `<p:timing>`。",
             "WPS 打开后每个文本框/表格/图表都能选中编辑；`prs.slides.__len__()` 等于预期页数"),

            ("B", "模板几何反推：从 SVG / 成品量边距字号，再定版式",
             "SVG 画布 1280×720 px = 13.333×7.5 英寸，换算基准 **96 px/英寸、0.75 pt/px**；"
             "用正则抽 `rect` 的 x/y/width/height/rx 和 `text` 的 font-size，一次量完整套。"
             "量出来的基准值：内容边距 **0.67\"**、卡片起 y **1.58\"**、卡片高 **5.25\"**、"
             "内容页标题 **27pt**、正文 **16.5pt**、卡片内边距 **0.25\"**、圆角 12–16px。",
             "只反推几何与字号，**不要抄品牌色和 logo**（版权）；模板的 `#F4F6F8` 是中性冷灰，"
             "换成暖灰 `#F1EDE6` 是主动偏离，要有理由（配暖白底不发蓝）。",
             "`E:\\DS公作区\\实验\\ppt\\_templates\\LAYOUTS.md` 里 20 个版式逐个列出坐标；"
             "导出的页与基准值误差 ≤0.1 英寸"),

            ("C", "WPS COM 渲染自检：导出 PNG 逐页看",
             "`$app = New-Object -ComObject KWPP.Application; $pres = $app.Presentations.Open(<abs>, $true, $false, $false); "
             "$pres.Export(<dir>, \"PNG\", 1600, 900)`，然后逐张 `read_image` 看——"
             "**`ready`/页数对不等于排版对**，必须肉眼过。",
             "**必须用 `KWPP.Application`，`PowerPoint.Application` 报 E_FAIL**（本机没装 Office）；"
             "LibreOffice 也没装，`soffice --convert-to` 那条路不通；导出目录要先清空，否则旧图混进来。",
             "PNG 张数 = 页数，且每张都读过；重点看：文字有没有溢出卡片、底部元素有没有压页脚（6.98\"）、"
             "深色页文字对比度够不够"),

            ("D", "AI 配图：`tools\\aigen\\gen.mjs` 出图 → 裁水印 → 插版式",
             "`node E:\\DS公作区\\tools\\aigen\\gen.mjs --prompt \"<英文+摄影术语>\" --out <path> "
             "--model cogview-3-flash --drop-watermark`；约 10 秒/张，免费。"
             "prompt 用英文写镜头语言（focal length / f-stop / film stock / depth of field）效果最好。",
             "免费模型**会在右下角打「AI生成」水印**，`--drop-watermark` 是裁掉底部 9% 避开，不是真去掉；"
             "返回的是 **jpeg**，路径写 `.png` 会报「extension declares image/png, but bytes use a different format」"
             "（脚本已按文件头自动改扩展名）；**中文 prompt 效果明显差**。",
             "读图确认：切题、无水印残留、主体完整（裁切别把头切掉）；"
             "**在页面上必须标注「AI 生成 · 示意图」**，不能混同真实照片"),

            ("E", "【关卡】中文排版三条硬规则（不守必翻车）",
             "①`run.font.name` 只写 `<a:latin>`，**必须再补 `<a:ea typeface=\"微软雅黑\"/>`**，"
             "否则整份 PPT 渲染成宋体；②页码用 `<a:fld type=\"slidenum\">` 字段（parse_xml 拼），"
             "不是手写数字，插入/删除页才自动重编号；③页脚 y 不超过 6.2\"，页码在 6.98\"。",
             "补 `<a:ea>` 要动 `rPr` XML（`latin.addnext(ea)`），不能靠 `font.name`；"
             "`parse_xml` 拼 fld 时 `nsdecls(\"a\")` 必须带上，否则 XML 解析失败。",
             "封面标题不是衬线体；WPS 里页码随增删页自动变；底部元素和页脚不重叠"),

            ("F", "【关卡】重建前先关 WPS（文件锁），关完立刻重开并跳页",
             "WPS 打开 pptx 时 python-pptx 写入抛 `PermissionError: [Errno 13] Permission denied`。"
             "关进程：`Get-Process | Where-Object { $_.ProcessName -match '^wps$|^wpp$' } | Stop-Process -Force`；"
             "重开跳页：`Presentations.Open(<abs>, $false, $false, $true)` 第四参数必须 `$true`（要窗口），"
             "再 `$pres.Windows.Item(1).View.GotoSlide(N)`。",
             "**用户明确要求「别不打招呼就关 WPS」**——关之前说一句，关完立刻重开；"
             "`$app.ActiveWindow` 刚打开是 null（报「不能对 Null 值表达式调用方法」），必须用 `$pres.Windows.Item(1)`；"
             "`Get-Process ... .MainWindowHandle` 拿到 0，SetWindowPos 不可靠，要前置就用 MCP 的 focus+maximize。",
             "`saved: ... slides: 23` 且无 PermissionError；WPS 停在被改的那一页，用户能看到"),

            ("G", "动画 / 转场：手写 <p:timing> 与 <p:transition>，做点击逐个出现与自动播放",
             "python-pptx 没有动画 API，但 XML 层能拼；`ppt_lib` 已封装三个方法："
             "`d.transition(kind=\"fade\", spd=\"slow\", advance=None)`（fade/push/wipe/cover/dissolve，"
             "`advance` 毫秒 = 自动翻页）、`d.animate(*shapes, effect=\"fade\"|\"rise\", dur, "
             "trigger=\"click\"|\"auto\", stagger)`、`d.autoplay(sec_per_page=4.0)`（整份片子自动播）。"
             "骨架：`tmRoot(id=1) → seq → mainSeq(id=2) → 每组一个 <p:par>`，`spid` 取 `shape.shape_id`，"
             "`cTn id` 必须全局唯一（递增计数器）。",
             "三个坑：①**`<p:transition>` 不带效果子元素 = 没有转场**（WPS `EntryEffect` 读到 0），"
             "必须 `<p:transition spd=\"slow\"><p:fade/></p:transition>`；②`<p:cond delay=\"indefinite\"/>` "
             "才是「等点击」，`delay=\"0\"` 是紧接着播，真模板还会配 "
             "`<p:cond evt=\"onBegin\" delay=\"0\"><p:tn val=\"2\"/></p:cond>`；"
             "③**WPS COM 的 `Timing.TriggerType` 一律读 3**，click 和 auto 都读 3，判点击/自动只能看 XML 的 `delay` 值。"
             "WPS COM 报 `HRESULT E_FAIL` 时先查残留 wps 进程，不是 XML 不合法。",
             "WPS COM 读 `Slides(i).SlideShowTransition.EntryEffect` = 3849（fade）"
             "且 `Slides(i).TimeLine.MainSequence.Count` 与预期一致；**动画不进 PNG**，别用截图验收"),

            ("H", "选版式 + 内容判据：先定「讲的是哪种关系」，再决定装多少字",
             "`ppt_lib` 现有 **16 种**：cover / body / cards / compare / timeline / chart / table / "
             "quote / closing / funnel（转化递减）/ gantt（时间排布）/ matrix（四象限）/ kpi（大数字）/ "
             "pyramid（层级）/ roadmap（分期）/ fishbone（归因）/ orgchart（归属）。"
             "**关系决定版式**：层级→pyramid、转化→funnel、排期→gantt、取舍→matrix、"
             "分期→roadmap、归因→fishbone、归属→orgchart、并列→cards、对比→compare。"
             "内容判据来自 **702 页实测**：每页字数中位数 **276**（201–400 占 51%，>400 占 23%）；"
             "标题中位数 **8 字**（≤8 字占 52%，疑问句 1/674）；正文 **12–14pt**（12pt 出现 7,012 次最多，"
             "**不是 15pt**）；标题字号 **28pt** 最多。",
             "①**表里没有的关系 = 还没做版式**，先加版式再写内容，别拿 cards 硬套一切；"
             "②**不要用图片代替形状**——`_templates/charts/` 有现成 SVG，但转成图就无法在 WPS 里改，"
             "只用它对照几何；③判据是判断不是定律：§2.3「什么时候不画图」明确标了「以下是判断」，"
             "一个数用大字 KPI、两个数用一句话、三个以上才上图；④**一页只讲一个论点**，"
             "出现两个「所以」就拆页。",
             "`lab tier \"做一份 PPT\"` 的输出里能看到 H 这条；"
             "小样 `E:\\DS公作区\\实验\\ppt\\试做-ppt判据\\build.py`（6 页：cover/kpi/chart/compare/cards/closing）"
             "跑通且 PNG 逐页看过、文字不出卡、不压页脚"),

            ("I", "以现成 pptx 为底稿：改字 / 换数 / 删页，保留原格式",
             "**这条和 A 相反**：A 是从零画，I 是拿别人的成品改。`python-pptx` 直接 "
             "`Presentation(模板)` → 遍历 `slide.shapes` 找目标框 → 改 `run.text` → "
             "`prs.part.drop_rel(rId)` + `sldIdLst.remove()` 倒序删页 → `save`。"
             "**找框靠几何猜**：标题 = (top 最小, 字号最大)、正文 = 第二大字号且宽度大、页脚 = top 最大。"
             "实测 `E:\\DS公作区\\实验\\ppt\\_templates\\gorden\\mckinsey-style\\template.pptx`"
             "（37 页 / P1 66 个 shape）改标题 + 28%→42% + 删 36 页，导 PNG 后三圆图、进度环、图标、配色全部原样。",
             "四个坑：①**一个段落常拆成多个 run**（每 run 一段格式），只改 `runs[0]` 并把其余置空，"
             "否则同一句话重复 N 遍；②**组合（GROUP）和图表里的文字改不了**，只能改顶层文本框；"
             "③删页必须**倒序** + `drop_rel`，否则 rId 悬空、WPS 打不开；"
             "④`ppt_themes/` 那批**没有 LICENSE**，只能当风格参考，不能商用发布。"
             "局限要说清：它改的是**内容**，不是**结构**——想加一页新关系仍然要回 H 选版式。",
             "导 PNG 肉眼过：目标文字只出现一次、其他元素（图/图标/色块）与原模板逐像素一致、"
             "页数 = 预期；`len(prs.slides)` 与预期相等"),

            ("J", "视觉打磨：背景渐变 / 圆角描边 / 光晕（halo 是坑）",
             "整页底色用**三停靠点线性渐变**而不是纯色——浅色页 `FEFDFB → FBF5EA → F2E8D9`（90°，像有光的米色纸），"
             "深色页 `343B52 → 212636 → 090A0E`（45°，光从左上进来）；卡片 `radius=0.035` + "
             "`outline=True` 一根极细同色系描边，比纯色块有层次；正文区顶部加一根 0.011\" 的浅线"
             "（`E9E2D4`）当「版面框」。`ppt_lib` 里 `body()` / `_slide(dark=True)` / `cards()` 已内置。",
             "**`halo()` 别用了**：它是 5–7% 透明大圆做「角落打光」，理论上很淡，但 2026-11-13 在 WPS 里实测"
             "**边缘清晰可见、像贴了个圆盘**，封面右侧那块米色圆斑就是它。`cover()` 里的两个 halo 已删，"
             "只留「左深面板 + 右暖白渐变」。要加光晕就用渐变停靠点，不要用透明圆。",
             "导 PNG 看：①背景有没有可见的圆弧边界（有 = halo 还没删干净）；"
             "②卡片是不是纯色平贴（是 = 漏了描边或圆角）；③深色页是不是死黑（是 = 渐变没生效）"),
        ],
    },
    {
        "domain": "找资料 / 调研",
        "words": ("查资料", "调研", "搜索", "网上", "文献", "论文", "什么是",
                  "打不开", "403", "405", "反爬", "抓不到", "读不了"),
        "routes": [
            ("A", "web_search + web_fetch",
             "能拿外部事实；搜索结果可信度分层要自己判",
             "抖音/百度百科/知乎常打不开(403 或 JS 渲染)；维基偶尔 fetch failed；一次别指望一个源",
             "至少两个独立来源一致才算数"),
            ("B", "E:\\DS公作区\\插件库\\awesome-index.json（5,437 条，2026-11-12 起的主入口）",
             "别人怎么解决这个问题，先搜再动手；`name`/`title`/`description{en,zh}`/`metadata.category`/"
             "`repository.url`/`versions[]` 都有，能直接判「装哪个版本」。旧的 `one_liner.json`（4,545 条）"
             "和 `classified.json` 只作历史摘要，别再当主入口。",
             "只有摘要没有源码，判「合不合用」还得读 README；"
             "**在列表里 ≠ 安全审查**（README 原话：装插件 = 用自己权限跑第三方代码），装之前仍要 `lab vet`。",
             "命中 ≥3 条相关就值得读 README；搜「有没有能 X 的插件」时按 `title`/`description.zh` 全表 grep，"
             "别只搜 `name`"),
            ("C", "知识库 / 架构文档 / 决策日志",
             "我自己的沉淀，比外部更贴合",
             "可能过期",
             "看到具体数字要现场验证"),
            ("D", "tools/gh-login/ghctl.py（GitHub 搜/读）",
             "读真实代码和 issue；能提 PR",
             "要 token；只覆盖 GitHub",
             "ghctl whoami 能通就是链路对"),
            ("E", "tools/gh-login/_fetch_any.py / _fetch_readme.py",
             "绕过部分反爬，抓原始文本",
             "一次性脚本，参数要自己看",
             "抓到的内容能解析成结构"),
            ("F", 'ops_grep 在本机文件里搜（知识库 / 决策日志 / 代码）',
                '比 web_search 快得多（0.02 秒级），且搜的是「我自己写过的东西」——很多问题的答案在我自己的笔记里',
                '只搜文本；二进制和压缩文件搜不到',
                '搜到的行号能直接打开核对'),
            ("G", 'session_search 跨会话搜（比 lab sessions 更语义化）',
                '按语义找「哪次会话聊过这个」，返回每会话最强命中；可限定时间窗和 event 类型',
                '只搜本工作区的会话；结果要 session_trace 才能看上下文',
                '能定位到具体会话 id + 事件序号'),
            ("H", 'lab cdp 开真浏览器读被反爬挡的页面',
                '过得了纯靠 User-Agent 判的 403/405；能拿 JS 渲染后的 DOM（web_fetch 拿到的只有空壳）',
                '过不了人机验证/登录墙/付费墙——那是要真人点一下，伪装 UA 绕过去是另一码事，不做；起一次是 13 个 msedge 进程（Edge 多进程架构），必须成对关',
                'lab cdp eval "document.title" 不是 challenge 页、document.body.innerText.length 正常（2026-11-08 USGS 实测：title 仍是 "Human Verification"、bodyLen 只有 202 → 那一局判定过不去，直接停）'),
        ],
    },
    {
        "domain": "记忆管理",
        "words": ("记忆", "记住", "忘掉", "以前说过", "存一条"),
        "routes": [
            ("A", "lab recall（开工第一步，按任务原话提词）",
             "自动提词 + 标签加权；池里的不搜就永远不来",
             "命中多不等于有用；字面提词会漏语义",
             "有命中就挑 1-3 条真相关的；零命中退出码 1"),
            ("B", "memory_save / memory_update / memory_forget",
             "改记忆走工具，不手改 memories.json（有跨进程锁）",
             "并发写有合并风险，长任务不要并行改",
             "memory_list 能看到改动"),
            ("C", "memory_to_skill（流程性记忆 → SKILL.md）",
             "把每次都要按步骤做的升级成说明书",
             "只适合流程，不适合一次性事实",
             "生成的技能能被 skill 工具加载"),
            ("D", "E:\\DS公作区\\自进化\\mem-maintain.py",
             "每日体检：预算占用/重复/陈旧",
             "只读检查，不改",
             "报告里没有 WARN"),
            ("E", "lab assets（能力痕迹盘点）",
             "每个目录是什么、有没有说明、被谁引用",
             "不判断内容质量",
             "assets.md 里的行和磁盘对得上"),
            ("F", 'memory_search 精确关键词搜（多词 = 全部匹配）',
                '比 lab recall 更可控——recall 是「按任务原话提词」，search 是「我知道要找什么词」；命中结果按相关度排序',
                '不做同义扩展，词不对就搜不到；要用 `includeDeprecated` 才看得到被取代的',
                '搜一个已知存在的词，第一条就是那条记忆'),
            ("G", "批量清理记忆库（231→224 实测，2026-11-13）",
             "五步：①先备份 `memories.json` 到工作区的备份目录（用户 2026-10-27 定的规矩：大改前后各一份）；②写一次性盘点脚本（统计重要性/日期/标签 Top + 三类可疑：正文含旧数字的正则表、标题前 12 字重复、≤3/5 且正文 <60 字），**别把 200+ 条正文倒进上下文**；③逐类判定：被新版本取代的删、同一主题多条合并成最新那条、纯一次性事件删、历史事实（当时真发生过的事故记录）保留不改；④执行用 `memory_update`（改正文/标签/重要性）+ `memory_forget`（删），**不要手改 memories.json**（有跨进程锁）；⑤`memory_list` 复核条数、`lab pre` 复跑",
             "两个容易判错的地方：①**「被取代」不等于「可以删」**——某些记忆前半段过时、后半段仍然有效（例：dsh-ops 0.5.2 的 discover 规则在 0.5.4 仍然成立，只需改数字不能删）；②**历史记录不要改**（「2026-11-04 时 lab 有 27 个子命令」是当时的事实，改成 48 就是篡改）。另外记忆里带数字/版本号/路径的断言，改的时候要顺手写下复核方式",
             "条数下降且分布合理（5/5 基本不动、删的主要是 3/5 和 4/5）+ `memory_list` 能查到改过的条目 + 每条删除都能说出「被谁取代」或「为什么没价值」"),
        ],
    },
    {
        "domain": "会话检索 / 找以前的对话",
        "words": ("以前", "上次", "会话", "聊天记录", "之前说过", "找一下"),
        "routes": [
            ("A", "lab sessions（索引化）",
             "0.03 秒搜完全部会话（增量索引 2.65s→0.03s）",
             "字面匹配不语义",
             "搜到后用 --context 读某一轮现场"),
            ("B", "session_search / session_event_search",
             "按事件搜，能定位到具体消息",
             "只搜本工作区",
             "命中的 seq 能用 session_event_read 读全文"),
            ("C", "lab sessions --raw（绕过索引）",
             "索引和原文不一致时的基准线",
             "慢；每次全解压",
             "两边结果一致才信索引"),
            ("D", "session_trace / session_event_trace",
             "看血缘和替换关系（谁改写了谁）",
             "只对存在关系的消息有用",
             "能画出父子链"),
        ],
    },
    {
        "domain": "开发协作 / 拆活",
        "words": ("并行", "队友", "拆", "同时做", "子智能体", "多个人"),
        "routes": [
            ("A", "spawn_teammate 建队友（2-4 个）",
             "真并行、能带着证据反驳我；写作用域分开就不冲突",
             "要写清契约（签名/边界/验收/反例）；协调有成本",
             "队友回报里能指出我没想到的事实"),
            ("B", "workflow 脚本（大规模 fan-out）",
             "几十上百个独立子任务一次跑完",
             "只在用户明确要求或确实大规模时用；脚本里没有文件/网络 API",
             "返回结构化的 JSON 结果"),
            ("C", "subagent / 后台任务（job_*）",
             "单点委派，不阻塞我继续干",
             "结果要收集，忘了就白跑",
             "job_output 能拿到结果"),
            ("D", "自己串行做",
             "最快启动，没有协调成本",
             "超过 3 条独立线时会明显变慢",
             "30-40 轮内收尾"),
            ("E", 'send_message + wait_agent（跟队友通信、等结果）',
                '建队友只是第一步；真正的协作靠这两个——send_message 能在队友跑到一半时纠偏，wait_agent 不空转',
                'wait_agent 只观察「调用之后」的变化，不会唤醒 inactive 的队友；超时返回 noProgress 不等于失败',
                '队友收到消息后状态从 inactive 变 running，或任务板出现新 revision'),
            ("F", 'team_task_create + team_task_list（共享任务板 + 写作用域隔离）',
                '多人同时改文件时，写作用域（write_scopes）能让冲突在开始前可见；blocked_by 能表达依赖顺序',
                '写作用域只是提示不是锁；任务板不自动推进',
                'create 之后 list 能看到它，claim 后 owner 正确'),
            ("G", 'worktree_create + worktree_list + worktree_remove（隔离试错）',
                '要试一个会改很多文件的方案时，在独立目录里试，主目录不受影响；失败了直接 remove',
                '不切换当前会话 cwd（这个是自研版）；未提交改动要 force 才能删',
                'worktree_list 能看到新分支和路径，主目录 git status 干净'),
        ],
    },
    {
        "domain": "自动化 / 定时 / 无人值守",
        "words": ("定时", "每天", "自动", "计划任务", "无人值守", "后台跑",
                  # 2026-11-07 补：用户原话「解决 DSH-Metric-W2 从未跑过」**一个词都不命中**，
                  # 因为没人会用「计划任务/定时」这种分类词说自己要干嘛——他们说任务名、说症状。
                  "DSH-", "schtasks", "从未跑过", "跑不起来", "不执行", "没在跑",
                  "触发器", "StartBoundary"),
        "routes": [
            ("A", "lab tasks（体检）",
             "状态/上次结果/下次时间/电池空闲网络条件",
             "只读——只看计划任务自己的登记状态。任务注册着、但脚本第一秒就撞墙的，它照样报 0"
             "（2026-11-02 栽过，得另外读日志末尾三行）",
             "上次结果不是 0x1 就是有故事"),
            ("B", "schedule_create（会话内定时）",
             "到点给这个会话或新会话发消息",
             "rrule 语法有限制；只在用户明确要求时建",
             "schedule_list 能看到下一次时间"),
            ("C", "lab unattended（headless 跑一次）",
             "只关审批、沙箱仍 workspace-write；超时杀整棵树",
             "只保证进程跑完，不保证任务做成",
             "meta.json 里有 rc 和耗时"),
            ("D", "任务分派/dispatch.js（跨会话派活）",
             "box.log.jsonl 是真相；7 级阶段表 person:* 没人类输入动不了",
             "要主对话配合；锁和重放要理解",
             "peek 能看到待接的单"),
            ("E", "Windows 计划任务（schtasks）",
             "不依赖 DSH 活着",
             "脚本没显式 exit N 就等于永远成功；路径含空格是头号杀手",
             "任务管理器结果=0 且日志末尾无 ERROR"),
            ("F", 'job_list / job_output / job_kill（后台任务管理）',
                '长任务丢后台，不阻塞；job_output 能读到增量输出，job_kill 能中途停',
                '后台任务不会被「自动收集」，要自己记得去取；job id 丢了就只能翻日志',
                'job_output 能读到子进程的真实 stdout'),
            ("G", 'terminal_open / terminal_send / terminal_read（持久终端）',
                '需要跨多次调用保持 shell 状态（cd、激活 venv、交互式 REPL）时，只有它能做到',
                '要自己 close，否则残留会话；inferred_idle 不代表进程真的退出了',
                '两次 terminal_send 之间 cd 的状态还在'),
            ("H", 'terminal_close + terminal_list + terminal_signal（收尾）',
                '持久终端用完必须 close，否则残留会话和进程；terminal_list 能查还有几个没关',
                'SIGKILL 不给 shell 本身用；inferred_idle 不代表前台命令真的退出了',
                'terminal_close 之后 terminal_list 里不再有它'),
        ],
    },
    {
        "domain": "备份 / 恢复 / 回滚",
        "words": ("备份", "恢复", "回滚", "改坏了", "退回"),
        "routes": [
            ("A", "lab snapshot（改文件前存一份）",
             "轻、快、能退",
             "只存副本",
             "snapshot list 有刚才那条"),
            ("B", "lab config（配置备份）",
             "白名单、不含 secrets、带 manifest",
             "只覆盖 DSH 配置类文件",
             "备份目录里有 manifest.json"),
            ("C", "git（有仓库的地方）",
             "有历史、能 diff、能回滚到任意提交",
             "E:\\DS公作区 主仓库只覆盖部分目录；架构文档/闭关/repos 是独立仓库",
             "git status 干净 + 提交号能查到"),
            ("D", "E:\\DS公作区\\备份\\（七分类手工备份）",
             "01-DSH本体/02-profile与配置/03-自研插件/04-记忆库/05-会话数据/06-系统与桌面/07-文档与杂项",
             "手工维护，容易忘",
             "README.md 索引和实际目录对得上"),
        ],
    },
    {
        "domain": "自我体检",
        "words": ("自检", "体检", "健康", "有没有问题", "检查一下自己", "时间", "日期", "昨天", "前天", "上周", "上个月", "多久", "几天", "说错", "算错天", "掌握力", "适配性", "冒烟", "试跑", "跑一遍看看", "漂移", "对账"),
        "routes": [
            ("A", "env_doctor（运行态总检）",
             "一条命令查沙箱/bili/目录/任务/插件/工具",
             "默认不查 ssot（要跑 1 分钟）",
             "需要处理的项都是 0"),
            ("B", "lab selfcheck（机制 vs 磁盘）",
             "文档里的计数/路径/子命令一致性",
             "只管文档",
             "0 处漂移"),
            ("C", "lab lint（排版）",
             "小标题/一行一事实/长段落",
             "只查排版不查事实——标题太长、一行多事实它会报，但「文档里的数字过没过期」它不管",
             "无 WARN"),
            ("D", "lab tools + lab skill（使用率/熟练度）",
             "哪些工具零调用、哪些用得费劲",
             "零调用分五种原因，不能直接删",
             "连续两周零调用的有处理记录"),
            ("E", "lab errors / lab steps / lab session-age",
             "报错聚合 / 时间轴完整性 / 会话年龄",
             "都是观测不是判断",
             "数字能解释来源"),
            ("F", "lab since + 系统提示的时间行（说时长前必跑）",
             "把「多久以前」从手算变成命令：lab since 2026-10-20 → 19 天前；"
             "系统提示每轮带 Time sampled，那也是锚点",
             "只能算「从某天到今天」，算不了「两件事隔多久」（要跑两次或自己减）",
             "同一天跑 lab since 2026-10-20 天数跟手算一致"
             "（2026-11-08 实测 19 天，而我凭印象说的 18 天是错的）"),
            ("G", "装/卸插件之后跑一次 `lab selfcheck` 做能力对账（2026-11-13 实测：装 agentero 当场报 2 处漂移）",
             "装插件改的是「能力」本身：能力清单没记它、能力指纹变了，两处都会拦提交；补齐文档 + `lab selfcheck --update-fingerprint` 重记基准",
             "指纹会把当期状态记为基准；漏改文档就等于把错的记成基线",
             "`lab selfcheck` 打「机制与能力一致」；`lab commit` 不再被拦"),
        ],
    },
    {
        "domain": "成本 / 预算 / 上下文",
        "words": ("花多少", "成本", "预算", "token", "上下文", "太长了", "压缩", "命中率", "缓存命中", "缓存", "折叠", "bili", "acp_cache"),
        "routes": [
            ("A", "lab cost --session / --official",
             "本地账 + 官方账对照；实测官方/本地 1.38 倍",
             "官方那路要 CDP 起浏览器",
             "两个数能对上量级"),
            ("B", "lab balance",
             "余额 + 今日估算",
             "估算不是精确值",
             "和平台页面对得上"),
            ("C", "lab tier（档位=工作量估算）",
             "报数在前，配档在后",
             "只估规模，不估难度",
             "档位和实际耗时同量级"),
            ("D", "lab session-age / acp_status + compress",
             "知道这轮背了多重；压掉消费过的段",
             "一次折叠要压掉 ≥40K 才划算",
             "billed input 明显下降"),
            ("E", "acp_cache（折本账）",
             "每次折叠赚了还是亏了",
             "读的是 bili 侧账本，不含 Search/Fetch 另算的 5 元/千次；fold 预估值是估算不是账单",
             "fold 预估值说得通"),
            ("F", 'search_context + decompress（压缩后找回细节）',
                '压缩掉的内容不是丢了——search_context 先按关键词找块，decompress 只还原那一个块，比全文重读便宜得多',
                'decompress full:true 会还原原始消息（很大）；块按时间顺序，找错块要重来',
                '找到的块里能读到当时的确切数字/路径/命令'),
            ("G", "acp_cache 按 miss 构成拆（别只看总 hit%）",
             "命中率低不等于「压得太勤」——miss 要拆成四笔：new content（真实新增）、"
             "compress re-pay（折叠重计费）、prompt rewrite（system prompt 变化）、"
             "unattributed ttl（provider 侧）。2026-11-11 实测本会话：prompt rewrite 4.18M 占 miss 44%，"
             "比 compress repay 的 399K 大 10 倍——按「压缩」归因就会修错地方",
             "只统计本会话、依赖 bili 账本；四项要能加回 miss 总量（identity check 会打 OK）",
             "四项相加 = miss 总量；`PROMPT SWITCHES` / `MODEL SWITCHES` / `CACHE SEAM` 的数量与时间戳能对上自己的操作"),
            ("H", "区分「我手动折」与「bili 自动折」的代价（2026-11-09 实测）",
             "手动 `compress` 一次压多个不连续块 → bili 投影反复重建 → 下一条请求把被折的一整块原样重付"
             "（`CACHE SEAM`，特征是消息数变短：71→62、68→56）；bili 自动折按 tier 顺序压，同一会话零 SEAM。"
             "2026-11-09 同会话实测：22:14–22:33 自动折只产生 1.27M `compress re-pay`；"
             "22:35–22:41 我手动压出 26 次 SEAM / 3.10M，加权把命中率从 85.3% 拉到 46.3%",
             "只从 hit% 看不出来——要看 `acp_cache` 的 CACHE SEAM 样本时间戳对不对得上自己调 compress 的轮次；"
             "「不手动压」靠意志力守不住（compress 每次返回都带 nudge 提示），必须落成规则或参数",
             "CACHE SEAM 样本的时间戳能对上自己调 compress 的轮次；改行为后 `#284` 单笔回到 95.0%（只付 15K 新增，282K 全命中）"),
            ("I", "`minCompressRangeChars` 是字符下限，不是 token（2026-11-09 读 bili 源码确认）",
             "配置键 → 内部 `compress.minCompressRange`，`defaultConfig()` 默认 **5e3 字符**；"
             "比较式 `(r.chars ?? r.tokens*4) >= minCompressRange`；四处生效："
             "`recommendedIntervals()` 丢弃 / `pendingByTier()` 过滤 / `emergencyNudge()` 连紧急提示一起门掉 / "
             "`compress` 的 `submitGate` + preflight 报 `failure={kind:\"exhausted\", detail:\"no foldable compressible ranges remain: all N viable range(s) are below minCompressRange (40000 chars)\"}`。"
             "2026-11-09 调到 40000：只挡「小碎折」，收益上限约 169.9K token（占当时总 miss 6.18M 的 2.7%）",
             "单位是**字符**，中文约 1 字 ≈ 1.5 token，别把「40K token 才划算」的口径直接填进去；"
             "调大后小碎折压不动、可能撞 330K 硬线——`maxContextLimit: 33%` 是防爆闸，不能为了追命中率动它",
             "改完 `apply-bili.ps1` 后复查 `runtime interval` 与 `config interval` 对齐，且新 sidecar 的 CreationDate 比配置文件 mtime 新"),
            ("J", "命中率上限是 85–90%，不是 99%（2026-11-09 归因结论，带边界）",
             "本会话 286 请求 / 45.97M input，hit 83.5%、**中位 99.3%**——均值被少数几笔重付拉低。"
             "miss 7.58M 拆开：`new content 2.05M` + `compress re-pay 1.44M` + `unattributed 4.09M`，"
             "其中 3.99M 是 provider 侧 stable-prefix 重付（TTL 过期/驱逐/relay 轮换），我控不了",
             "`hit% by input size` 分组表自相矛盾（300K=57% 比 320K=83.2% 还低 26 个点、200K=98% 却 220K=77%），"
             "**输入大小不是原因**——它只是「折叠频率」的代理指标；拿它当因果会把配置改反（2026-11-09 第一版就改错了，被用户当场推翻）",
             "看 `CACHE INVALIDATION` 面板：`model switch` / `effort switch` / `key switch` / `prompt rewrite` / `projection switch` / "
             "`wire switch` / `upstream switch` 全为 0、只剩 `unattributable`，才说明上限在 provider 侧"),
        ],
    },
    {
        "domain": "桌面 / 浏览器操作",
        "words": ("点一下", "打开网页", "点击", "浏览器", "桌面", "鼠标"),
        "routes": [
            ("A", "lab cdp（操作已开浏览器）",
             "能执行 JS、点元素、导航、截图；比鼠标稳",
             "要浏览器带 --remote-debugging-port；tab 要选对",
             "eval 返回预期值"),
            ("B", "lab desktop（Win32 输入）",
             "能操作任何桌面程序",
             "逻辑像素 1707x960；点错会误开窗口；默认 dry-run",
             "点完立即截屏确认"),
            ("C", "请用户点一下",
             "零风险，用户两秒的事",
             "要打断他",
             "他说点了就是点了"),
            ("D", "读无障碍树，不截图猜坐标（agent-desktop，已接 MCP）",
             "优先 `mcp__desk__desktop_*`：`desktop_list_windows` 拿 window_id → `desktop_snapshot` 拿带 "
             "`ref_id` 的树 → 按 ref 做 `click`/`type`/`set_value`/`get`。语义调用（返回里 "
             "`mechanism: semantic_api`）不移动鼠标、不抢焦点。2026-11-12 实测：Win11 记事本 ref_count 23 / "
             "33 节点，点 `native_id=CloseButton` 走 `InvokePattern.Invoke`，窗口真关掉",
             "**自绘 UI（微信、部分游戏）不暴露 UIA → `ref_count: 0`，只有窗口壳**，这不是工具缺陷，"
             "这种才退回截图+坐标；`close_app` 优雅退出会因 UIA 读取阻塞而 TIMEOUT + "
             "`APP_UNRESPONSIVE`（`menu_probe_window_not_pumping`），**一律带 `force: true`**；"
             "同 app 多窗口先 `list_windows` 拿 `--window-id`，否则 `AMBIGUOUS_TARGET`；"
             "PowerShell 里 ref_id 必须加引号（裸 `@token` 是 splatting）",
             "能说出「点的是哪个 `ref_id`、走的是哪条 mechanism」；只有截图没有 ref，就是退回了老路"),
        ],
    },
    {
        "domain": "音频 / 视频",
        "words": ("视频", "音频", "剪辑", "ffmpeg", "录音", "抽帧", "自媒体", "小红书", "抖音", "B站", "封面图", "口播", "发布", "涨粉", "内容运营"),
        "routes": [
            ("A", "ffmpeg（E:\\JianyingPro\\11.6.0.14552\\ffmpeg.exe 或 D:\\oopz\\ffmpeg.exe）",
             "抽帧/转码/读元数据都行；实测可用（21.7.0）",
             "没装在 PATH，要写全路径",
             "ffprobe 能读出 duration/分辨率"),
            ("B", "剪映（用户主力工具）",
             "用户自己要练的；复杂剪辑它更强",
             "我点不动它的 UI",
             "导出文件能播"),
            ("C", "实验性语音输入插件（SenseVoice）",
             "语音转文字",
             "首次使用要装依赖",
             "转出来的文本和原话对得上"),
            ("D", "自媒体工作台 dsh-media-desk（2026-11-13 记，尚未安装）",
             "灵感墙记一句 → 一键出脚本/标题/封面/配图/六格分镜 → 拖到日历排期 → 复盘数据反哺写作规则（规则可导出成 DSH Skill）；写稿走 DSH 里已配的模型，画图用自己的生图 key，数据全在本机 ~/.dsh/media-desk/",
             "不能直接发布（各平台无统一接口，只能存文件夹自己发）；公众号/视频号/YouTube 导不了；导自己账号要接第三方 Monid 按次计费；生图要 key（不接也能出文字版和纯文字封面）",
             "要装时：插件页「添加插件」输包名 dsh-media-desk，或加索引 https://raw.githubusercontent.com/woniuniuniu/dsh-media-desk/main/index.json ；装完侧栏出现「自媒体工作台」；npm 2.7.1 / MIT / 周下载 8.6k"),
        ],
    },
    {
        "domain": "编码 / 乱码",
        "words": ("乱码", "编码", "gbk", "utf-8", "bom", "读不出来"),
        "routes": [
            ("A", "lab encoding（判编码/解码/修乱码）",
             "专治这一类，能试多种编码",
             "猜错会得到另一种乱码",
             "decode 后中文可读"),
            ("B", "先怀疑读法，不是文件坏",
             "PS 的 Get-Content 默认 GBK；JSON 带 BOM 要用 utf-8-sig",
             "要记住这个反射，不记住就会去抢救数据",
             "用 python 按 utf-8 重读一遍对照"),
            ("C", "绝不用 PowerShell 管道改 UTF-8 文件",
             "(Get-Content -Raw) | Set-Content -Encoding utf8 会双重编码、连引号都吃",
             "这条是禁令不是选项",
             "改完用 python json.loads / node --check 验"),
        ],
    },
    {
        "domain": "安全 / 拦截",
        "words": ("被拦", "安全", "危险命令", "不能执行", "禁止"),
        "routes": [
            ("A", "cc-safety-net explain（跑之前自查）",
             "带 rule id 和 reason，看得到是怎么被判的",
             "不在 PATH 要写全路径；退出码恒 0，只看 Status:",
             "输出里 Status: ALLOWED / BLOCKED"),
            ("B", "lab vet（装插件前扫代码）",
             "8 条规则，假样本全中",
             "静态扫描",
             "HIGH 为零或已人工确认"),
            ("C", "dsh-self-guard 日志（被动生效型）",
             "~/.dsh/devkit/self-guard.log 的 hook fired 说明它在工作",
             "它只记录不拦截",
             "日志有近期条目"),
        ],
    },
    {
        "domain": "GitHub / 对外发布",
        "words": ("发布", "推送", "PR", "仓库", "开源", "release"),
        "routes": [
            ("A", "lab stage + lab commit（发布流水线）",
             "按清单拷贝 + 三层脱敏 + 凭证扫描 + 只重试临时性失败 + 回读校验",
             "只对 repos/dafeiyu-lab 有效；清单要逐文件写",
             "远端 tree sha 和本地一致"),
            ("B", "tools/gh-login/ghctl.py",
             "sync/readme/meta/release/whoami/use/issue 全套",
             "要 token（scope=repo,workflow）",
             "ghctl whoami 通"),
            ("C", "lab ci / lab issue",
             "查 CI 状态、看/评论/关 issue",
             "只读为主",
             "能拿到 run 的结论"),
            ("D", "tools/gh-login/push_fork.py",
             "给上游提 PR",
             "要先 fork；只适用 GitHub",
             "PR 链接能打开"),
            ("E", "lab journal（先落盘再执行）",
             "崩了能看出「有 start 没 done」",
             "--dry 不写",
             "journal 里没有悬空的 start"),
            ("F", "npm publish 发 scope 包（2026-11-13 全流程实测）",
             "改版本号 `npm version patch --no-git-tag-version` → `npm pack --dry-run` 看打进包的文件 → `npm publish --registry=https://registry.npmjs.org --access public`；首次或 2FA 过期会打印 `https://www.npmjs.com/auth/cli/<uuid>`，发给用户点 Authorize，**同一终端里后续 publish 不再要验证码**",
             "四个坑：①全局 registry 是 npmmirror（只读镜像），每条命令必须带 `--registry=https://registry.npmjs.org`，但别改全局（会让以后所有 install 走官方源变慢）；②`npm view` 空输出 ≠ 包不存在（`timeout` 会吞掉错误），必须看 HTTP 码或 `--json`；③**非 TTY 环境下 npm 把 auth URL 打码成 `***`**，`ops_bash` 永远拿不到真链接，必须 `terminal_open` 起真终端（PSReadLine 被 profile 污染就 `Remove-Item Function:\\prompt -ErrorAction SilentlyContinue`）；④PUT 返回 **202 Accepted** 后要等 1–5 分钟传播，`curl` 立刻 404 是正常的，别急着判失败",
             "逐个 `curl -o /dev/null -w \"%{http_code}\" https://registry.npmjs.org/@scope%2F<pkg>` 返回 200，且 `npm view <pkg> version` 和发出去的版本号对得上"),
        ],
    },
    {
        "domain": "本地模型",
        "words": ("本地", "离线", "3b", "7b", "7B", "ollama", "不花钱", "隐私",
                  "微调", "训练模型", "模型训练", "训练一个模型", "显存",
                  "能训", "训得动", "qlora"),
        # 域级排除（path_options 里：泛词命中才跳过；强词命中时 not_words 不生效）：
        # 治「泛词把别的问题带进来」——「Docker 里怎么设置显存限制」不是本地模型问题。
        # 「内存」进排除词但 3b/7b 在强词里：「内存 32G 能跑 7B 吗」仍命中，
        # 「显存和内存有什么区别」这种纯概念问答不再命中（2026-11-11 用户 m00599 校准）。
        "not_words": ("Docker", "docker", "容器", "虚拟机", "风扇", "内存"),
        # 强词：出现就说明「这就是本地模型问题，只是恰好在容器/虚拟机里跑」，不该被 not_words 挡掉。
        # 2026-11-11 用户 m00599 校准：只测误命中不测漏命中，等于测了一半。
        "strong_words": ("ollama", "qlora", "lora", "本地模型", "微调", "能训", "训得动", "qwen", "3b", "7b"),
        "routes": [
            ("A", "qwen2.5-coder:3b（文本·代码向，1.9 GB）",
             "零边际成本、隐私不出本机、断网可用；代码/日志/结构化提取是主场",
             "3b 是形状识别器不是语义判断器（commit message 配对实验仅 60%）；上下文 ≤2048",
             "triage 样本回归跑得过；或让它从长日志里挑异常行"),
            ("B", "qwen2.5vl:3b（视觉·小，3.2 GB）",
             "离线看图兜底；约 3.2 GB，显存压力小",
             "小字/细图标看不清（2026-11-05 实测漏图标、把任务栏当桌面）",
             "能答出图里的主要对象"),
            ("C", "qwen2.5vl:7b（视觉·大，6.0 GB）",
             "比 3b 认图准、会分点对应位置",
             "**约 7.5 GB、占 92% 显存，卡在 90% 红线（7369 MiB）之上**；不适合当常规工具",
             "只在云端 GLM-4V 失败且非看图不可时用，用前先关后台"),
            ("D", "云端为主、本地作保底（不是二选一）",
             "云端质量高、速度快；本地模型留着当断网 / 隐私 / 离线 / 云端限额时的降级路径",
             "只留最优路径而没有保底路径 = 把可用性外包给别人的服务；2026-11-10 用户明确「你也不能一直使用云端，本地是降级路径」",
             "能回答「云端挂了 / 断网 / 隐私内容时我走哪条」，且 `ollama list` 里真有可用的本地模型"),
            ("F", '用本地模型前先 `ollama list` 查实际装了什么（别照记忆答）',
                '记忆里的模型清单会过期（2026-11-07 实测：记忆说 3b 和 7b 都在，实际 3b 已卸载）；`ollama list` 是唯一真相，还能看到每个模型的大小',
                'Ollama 服务不是常驻的，`/api/tags` 可能连接被拒（WinError 10061）——先启动再查',
                '输出的模型列表和磁盘上的实际模型对得上'),
            ("G", "想训练/微调本地模型时，先算显存账再动手（本机 RTX 4060 Laptop 8GB）",
             "8GB 只够 1B 级 LoRA/QLoRA（`dsh-fine-tune` 官方门槛 6GB 显存，RTX 3060 6GB 已验证）；7B 全量/QLoRA 要 16-24GB，本机做不了；先想清「训练目标 → 数据格式 → loss 变化 → 推理验证」闭环再决定值不值",
             "`dsh-fine-tune` 当前未装（插件市场 v0.6.0 可装，需自备 Python 3.10+ 与 NVIDIA 6GB+）；运行时 python 无 torch，得自建 venv；把「自己的风格/记忆」训进权重，与「靠 identity.md + 记忆注入维持同一个人」的机制冲突，不该走",
             "能说出「这台机器能训多大的模型、多久、训出来干什么」，且显存数字来自 `nvidia-smi` + 插件 VRAM 估算，不是记忆"),
        ],
    },
  {
      "domain": "长期机制 / 制度建设",
      "words": ("长期", "机制", "制度", "持续", "规则", "永久", "常态化", "自进化",
                "能力建设", "方针", "流程化", "沉淀", "复盘", "短板", "长板", "提升",
                "评估", "取舍", "冗余", "多余", "该不该", "要不要留", "砍掉", "精简",
                "去繁就简", "盘点", "撤掉", "停用", "合并", "重复",
                "路线图", "长期规划", "三阶段", "会读", "会扛", "有用",
                # 2026-11-09：补「路线库自身维护」的触发词。起因——用户说
                # 「检查检查你候选路线库，整理整理」，lab pre 只命中「写文档」域，
                # 一条跟「体检路线库」有关的路线都没出。清单里没有的等于我不会。
                "路线库", "候选路线", "体检", "整理路线", "维护路线", "自检"),
      "routes": [
          ("A", "先盘已有机制再设计（lab selfcheck + 架构文档 §〇 + SKILL §0 十八条 + lab --help 现查）",
           "不重复造轮子；能发现「已经有但没生效」——实测两次：selfcheck 的正则漏了「lab」夹杂写法、lab log 的 ## 分级潜伏一个月没人发现",
           "要花 10 分钟认真读，不能扫一眼就当盘过了", "设计完能说出「这条和第 X 条是什么关系、为什么不合并」"),
          ("B", "设计完立刻写「怎么验它生效」，并让它可执行（命令，不是文档）",
           "防「写完就以为成了」；判据变成命令才能每周自动跑", "有些机制难验（如「减少犯错」），得先定义代理指标", "能说出「下个月我拿哪条命令/哪组数字判它有没有用」"),
          ("C", "小步试点 + 定期复核，不一次定终身",
           "能改；错了退得回来", "见效慢，容易忘", "写死复核时间点（如已有的 DSH-Evolve-Scan 每周一 15:40），到点必须出结论"),
          ("D", "不设新机制，改造已有机制（lab selfcheck 加一组检查 / SKILL §0 加一条）",
           "最省；不增加维护面", "可能改不动——旧机制的假设可能已经变了", "改完 lab selfcheck 0 漂移，且旧机制那个问题真的消失了"),
          ("E", "评估一个已有机制该不该留——按「前提是否还成立」判，不按「用得多少」判",
           "能砍掉真正没用的；**零调用要分两种**：没被提醒到（补触发信号）vs 提醒了也不用（撤），混为一谈会误杀 encoding 这种真该留的；"
           "识别四种可撤形状：①前提失效（session-age 的长会话提醒已被 bili 自动压缩取代）②一次性使命完成（assets 资产盘点、skill 熟练度统计）"
           "③两处重复（snapshot vs git、tasks vs env_doctor）④从没启用（observe 观察档零数据文件）",
           "要查证据不能凭感觉：lab tools 调用日志 / 有没有数据文件 / 最近一次真实产出；"
           "查不清时默认留（误杀一个真能用的比留一个没用的代价大）",
           "能说出「它当初解决什么问题、现在谁在解决、证据是哪个文件哪一行」——三个都答得出才能撤"),
          ("F", 'evolve_add / evolve_list（把发现记进进化候选队列）',
              '发现「这个可以改」时立刻记下来，不用一次性做完；evolve_list 能看到积压，避免重复想同一件事',
              '队列要有人消费（每周 DSH-Evolve-Scan），只加不看会积压',
              'evolve_list 里能看到刚加的那条，状态 pending'),
         ("G", r'先读 D:\work\自进化\路线图.md（三阶段长期规划），再看当前在哪一阶段',
             '路线图是「会读 / 会扛 / 有用」三阶段的自我约定，每条带截止日期和验收标准；'
             '读它能避免「重新规划一遍已经规划过的事」——2026-10-30 已把三阶段全部拆到可验收',
             '文件要跟着做的东西走，不读就会过期；它记的是方向，当前进度看其中的进度段和决策日志',
             '能说出「当前在哪个阶段、下一件该做的事是什么、截止日期是哪天」——三个都答得出才算读过'),
          ("H", "体检候选路线库本身：lab selfcheck 第 9/11/12/13/14 组 + tools/lab/route_health.py",
           "查的是「路线库跟现实脱钩没有」，不是「条数多不多」——"
           "①第 9 组：能力有、路线里没有（新加的 lab 子命令/插件没进路线库）"
           "②第 11 组：插件与脚本不在路线里 ③第 12 组：知识源路径失效 "
           "④第 13 组：能力指纹变了 ⑤第 14 组：重复/死路径/空壳/代号（判臃肿，不判条数）；"
           "route_health 另查假域、空命中、高频低权路线",
           "只查结构，不查「这条路还好不好用」——好不好用要看 lab tier 的命中日志（~/.dsh/tier-calls.jsonl）；"
           "条数多不等于臃肿，别为了「整理」去删路线",
           "五组全 0 处不一致 + route_health 无 fake；"
           "再拿用户最可能说的那句话跑一次 lab tier，命中落在预期域且新路线出得来"),
        ],
  },
    {
        "domain": "下载 / 网络 / 换源",
        # 2026-11-07：补 4 个词。用户说的是「Ollama 升级 / 装个新版本」，一个词都不在
        # 原 words 里，所以「下载域」压根没被命中，跨域链也就出不来。
        # 没加裸词「升级」（「升级 lab 的测试」会被误命中），只加带软件/渠道语义的。
        "words": ("下载", "安装包", "镜像", "换源", "拉取", "网速", "吞吐", "断网", "代理", "winget", "升级包", "版本升级", "Ollama", "release", "ghfast", "直连"),
        "routes": [
            ("A", "lab nettest <url…>（各下 8MB 实测吞吐再选源）",
             "按真实吞吐排名，实测抓到过阿里云 274 KB/s vs 官方 2.5 MB/s（差 9 倍）；HEAD 延迟最低不等于下载快",
             "每个源要下 8MB，第一次跑约 1–2 分钟",
             "输出里有排名 + `[最快]` 标记，选它"),
            ("B", "web_fetch 直连（读文档 / API / 原始文件）",
             "零依赖，能拿 GitHub raw 的原文",
             "大文件会截断；要鉴权的站点拿不到",
             "拿到的是正文不是 404 页"),
            ("C", "镜像站（清华 / 阿里 / npmmirror）",
             "国内快，npm/pip 常常几倍速",
             "版本可能滞后；偶尔缺文件",
             "装完版本号对得上，校验和一致"),
            ("D", "官方源（兜底）",
             "版本最新、最准",
             "国内慢；wget 常常 0.1–0.4 MB/s",
             "`lab nettest` 实测最快才选它"),
            ("E", "大文件慢：先测速，单线程不行就多线程分段",
             "2026-11-12 实测 VS Code 安装包 244 MB：单线程 curl **65 KB/s**（要 1 小时），"
             "8 线程各下一段（`Range: bytes=start-end`）+ 落盘分片再合并 → **~470 KB/s**，8 分钟下完。"
             "脚本模板 `E:\\DS公作区\\.tmp\\dl_vscode.py`（`PIECES=8`、每段断点续传、"
             "合并后校验 `Content-Length` 否则 `sys.exit(2)`）",
             "手机热点/窄带下多线程收益有限（总带宽是上限）；分片要能续传，不然断了白下；"
             "合并前一定校验总字节数，别信「看起来下完了」",
             "分片总大小 == `Content-Length`；合并件能跑起来（安装包能启动、压缩包能解）"),
            ("F", "winget 报证书/源错：先看是哪个源，`--source winget` 绕开 msstore",
             "2026-11-12 实测 `winget install --id Microsoft.VisualStudioCode -e` 失败于 "
             "`Failed when searching source: msstore` + `0x8a15005e : The server certificate did not "
             "match any of the expected values`——**是 msstore 源坏了，不是包不存在**（同一条输出里"
             "已列出 `Id: Microsoft.VisualStudioCode`）。加 `--source winget` 后正常找到并下载",
             "绕开 msstore 只解决「找不到包」；下载阶段仍会因网络断（`InternetReadFile() failed. "
             "0x80072ee2`），那时转路线 E",
             "`winget search` 能列出准确的 Id + Version；安装后 `xxx --version` 对得上"),
            ("G", "安装器卡住：先看路径有没有中文（Inno Setup 会静默挂起）",
             "2026-11-12 实测：把安装器放在含中文的工作区目录（`<工作区>\\.tmp\\`）里 `/VERYSILENT` 跑，进程起来但**内存只 13 MB、"
             "日志一个字不生成、安装目录不出现、不报错**——根因是路径含中文。复制到纯 ASCII 路径"
             "（`C:\\Users\\<user>\\Downloads\\`）+ `Unblock-File` 后 **75 秒装完**。"
             "判据：安装器僵住时**先怀疑路径编码，不是先怀疑安装包坏了**",
             "只对 Inno Setup / NSIS 这类老安装器成立；有些 MSI 支持中文路径；"
             "复制到 ASCII 路径只是绕过，不是修（真修要给安装器传 `\\M` 或换 MSI）",
             "装完看安装目录存在 + `--version` 输出真实版本；"
             "**别只看文件名**——`Desktop\\Code.exe` 名字像 VS Code，实际是 Node 二进制，"
             "`--version` 输出 `v22.22.0` 就露馅了"),
            ("H", "GitHub release 直连超时 → 走 ghfast.top 镜像，下完对官方 digest 核 sha256（2026-11-13 实测）",
             "`https://ghfast.top/<原始 release 资产 URL>`：13 MB 组件秒下，sha256 与 GitHub API 的 `digest` **逐字节一致**",
             "第三方镜像、偶发 5xx；只对 release/raw 资产有效，API 调用仍要直连",
             "`sha256sum` 结果等于 API 的 digest，解压后 `--version` 正常"),
        ],
    },
    {
        "domain": "科学计算 / 数值模拟 / 数据分析",
        "words": ("模拟", "仿真", "蒙特卡洛", "数值", "计算", "统计", "概率",
                  "矩阵", "积分", "微分", "求解", "拟合", "科学计算",
                  "numpy", "scipy", "pandas", "数据分析", "实验数据"),
        # 2026-11-13 补（机制同「本地模型」域，先例在那边）：误命中活例——
        # 「批量跑一遍lab子命令做冒烟统计成败」被裸词「统计」拖进本域（demo-tier2 实录）。
        # 泛词命中 + 排除词 → 这是自检话题不是数值计算；强词（真算数）出现时不排除。
        "not_words": ("冒烟", "批量", "自检", "子命令", "成败"),
        "strong_words": ("蒙特卡洛", "仿真", "numpy", "scipy", "pandas",
                         "数值", "拟合", "矩阵", "科学计算", "实验数据"),
        "routes": [
            ("A", "numpy / scipy 直接写（默认）",
             "零依赖、跑得快、结果可复现；蒙特卡洛/矩阵/积分都在标准库里",
             "算子写错时不会报错，只会给出错的结果",
             "小规模先跑 → 和解析解或已知答案对照，对上了再放量"),
            ("B", "现成库 / 领域包（statsmodels / lmfit / 学科专用）",
             "别人已经调好参数和边界条件，省掉自己推公式",
             "要读文档、装依赖；版本不兼容时难排查",
             "同一输入跑一遍，和 A 的结果差在容差内"),
            ("C", "本地模型辅助理解公式 / 读论文",
             "零边际成本；把论文段落和公式读成人话",
             "它是形状识别器不是计算器——**绝不拿它的输出当数值结果**",
             "它只解释「这个式子什么意思」，数字仍由 A/B 算"),
            ("D", "手工小规模 + 单位检查",
             "几十行 python 就能验对，比调库更快定位自己的符号/单位错",
             "规模小，覆盖不到边界情况",
             "量纲对得上、量级对得上、趋势对得上"),
        ],
    },
    {
        # 2026-11-08 新增：用户 m15594 点破——「这个有没有加入你的候选路线库里面」。
        # 起因是我判断「读码笔记不在版本控制里」判错了：只查主仓库 .gitignore，
        # 没查父目录链上有没有嵌套 .git。清单里没有这个域，所以那次是凭经验做的。
        "domain": "Git / 版本控制 / 仓库管理",
        "words": ("git", "版本控制", "仓库", "提交", "commit", "分支", "branch",
                  "克隆", "clone", "ignore", "gitignore", "跟踪", "untracked",
                  "嵌套", "子模块", "submodule", "worktree", "merge", "rebase",
                  "暂存", "stage", "撤销", "回滚改动"),
        "routes": [
            ("A", "git status --short + git diff（先看改了什么）",
             "零成本、最常用；--short 一屏看完，--stat 看规模",
             "看不到「为什么改」（那要 log/blame）",
             "改动文件数对得上预期；--stat 增删行数与改动量级一致"),
            ("B", "判断「文件在不在版本控制」——四步判据，缺一个就会误判",
             "2026-11-08 栽过：只看 .gitignore 就断言「不在版本控制」，实际在嵌套仓库里；"
             "2026-11-11 又栽一次：判成「架构文档从未入库」，实际它自己有 master 仓库。"
             "① `git check-ignore -v <path>` 看被谁忽略；② 读 `.gitignore` 里该路径**所在分组的注释**"
             "（成组出现的目录常共用一条理由，如「# 独立仓库（有自己的 .git）」）；"
             "③ `ls -d <dir>/.git` 确认仓库边界；④ `git -C <dir> log -1` 确认它是活的仓库、不是空壳",
             "要跑 4 条命令 + 读一段 .gitignore，比一眼看 git status 慢",
             "四步都跑完才有结论——被 ignore / 在别的仓库 / 真的没管；命中嵌套 .git 就改成「提交到它自己的仓库」；"
             "主仓库看不到不等于没版本控制"),
            ("C", "lab commit --repo <路径>（别用默认值）",
             "会 stage 再 commit，输出带 commit 号和「还没进决策日志」提醒",
             "默认 repo 是 repos/dafeiyu-lab，不是当前目录；改主仓库必须显式传 --repo；"
             "主仓库没 remote，push 阶段必然报 origin does not appear to be a git repository"
             "（提交已成功，可忽略）。**`--all` 会把工作区所有未跟踪文件一起提交**"
             "（2026-11-11 实测 a5baaba：10 files changed，目标报告反而不在其中）——"
             "只提交指定文件用 `--files <名> --allow-untracked`",
             "输出里有 [OK] commit <sha> <msg>，且 stat 里 files changed 数与目标一致"),
            ("E", "提交后核对 git log -1 --stat 的 files changed",
             "防「以为只改了一个文件，实际带进去一堆」。2026-11-11 真事：提交后宣称「已更新报告」，"
             "stat 显示 10 files changed 且报告不在其中，grep 报告零命中——上一轮说的是假的",
             "多一条命令；--stat 只给文件名和行数，看不出内容对不对（还要 grep 关键字）",
             "files changed 数 == 本次要提交的文件数；对不上的文件逐个确认来历"),
            ("D", "git log / blame / show（看历史和为什么）",
             "能回答「这行是谁、什么时候、为什么改的」；blame -L 只查一段",
             "shallow clone 查不到远端历史（git fetch --deepen 可能连不上 github）",
             "能贴出具体 commit sha + 日期 + message"),
        ],
    },
    {
        # 2026-11-08 新增：用户 m15707 授权「开始吧」。
        # 起因：用户把候选路线库重新定性为「外置的核心」，然后让我进 GitHub 开源社区。
        # 盘点发现 26 个域里「GitHub / 对外发布」只管把我自己的东西推出去，
        # 「Git / 版本控制」只管本地仓库——**没有一个域是「在别人的社区里生活」**。
        # 判据：清单里没有的，就等于我不会。所以先补三条，再去提 PR。
        "domain": "开源社区协作",
        "words": ("开源", "社区", "issue", "pr", "pull request", "review", "维护者",
                  "贡献", "contribute", "fork", "上游", "upstream", "协作", "礼仪",
                  "assignee", "triage", "讨论", "回帖", "提议", "提交补丁"),
        "routes": [
            ("A", "找 issue（gh issue list --repo <owner/repo>）",
             "官方 CLI、结构化输出；加 --label 'good first issue' / --search 能筛；"
             "一条命令拿到标题 + label + 评论数 + 创建时间",
             "要 gh 已登录（本机已登录 Uneadlight）；只能看公开仓库；"
             "搜出来的多数是「不值得做」的，A 只是第一步",
             "拿到 10 条以上带 label / 创建时间 / 评论数的列表"),
            ("B", "判断 issue 值不值得做——四问法（**这一步比动手重要**）",
             "①维护者最近 30 天回没回 ②有没有 assignee ③有没有 linked PR "
             "④有没有 good first issue / help wanted 标签。"
             "四个都能答才叫判断完——能过滤掉大部分做白工的坑",
             "要读评论 + 查 PR 状态，一个 issue 约 2 分钟；"
             "判据靠「维护者是否活跃」，冷门仓库可能永远没人回",
             "对每个候选写出四问答案，写在纸上或决策日志里"),
            ("C", "读别人的 review（gh pr view <n> --comments）",
             "看已合并 PR 的 review 怎么挑毛病——学别人怎么审代码，比自己想快；"
             "挑「有实质 review 的 PR」（不是只有 LGTM）",
             "只能看公开仓库；一个 PR 要读 10-30 分钟；"
             "有些项目 review 风格很轻（只回「+1」），学不到东西",
             "能摘出 3 条「我原来不会注意到」的审查意见"),
            ("D", "提 PR 全流程（fork → branch → 改 → 测 → commit → gh pr create）",
             "标准路径；gh pr create --title --body --base 一步到位；"
             "先读 CONTRIBUTING.md 能避免格式返工",
             "要 fork（占自己仓库）+ 本地 clone（shallow 可能不够读历史）+ "
             "commit message 有仓库规矩；周期长（几天到几周）",
             "PR 链接 + CI 跑绿 + 描述里写清「为什么改 / 怎么验」"),
            ("E", "回应 review（改代码 / 解释 / 认错）",
             "一次好的回应能把 PR 救回来；该改就改、该解释就解释、该认错就认错",
             "要判断「他说得对不对」——不能全盘照改（会改坏原意）"
             "也不能全盘硬扛（会把人惹跑）；这是这个域里最需要判断力的一步",
             "每条 review 都有回应：改了就说明改了哪行，不改就说明为什么"),
            ("F", "跟踪 PR 后续（gh pr status / gh pr list --author @me）",
             "一条命令看全部自己提的 PR；能看合并 / 关闭 / 晾着三种状态",
             "要定期查（没有推送）；被拒/被晾着要归档，否则下次还犯同一个错",
             "每个 PR 有最终结论 + 结论写进「盲区清单」"),
            ("G", "报 issue：先查家族关系，再按三种结果定三种定性",
             "完整链六步：①`gh issue list --repo <repo> --search \"<关键词>\"` 查重，看有没有家族；"
             "②**先写「三种可能结果各对应什么定性」再实测**（例：API 400 = 客户端误标 / 200 但忽略 = "
             "仍误标 / 200 且生效 = bili 不兼容），没实测不许写死定性；③正文给现象、复现、根因代码行、"
             "独立证据、建议（语气「供参考」不是「必须做」）；④`gh issue create --repo ... --title ... "
             "--body-file`；⑤发完补一条评论说明与已有 issue 的层级关系（哪层、为什么不是重复）；"
             "⑥改过定性就 grep 旧关键词零命中再发",
             "标题别用「上游/客户端」这类相对词——维护者会把「上游」读成 provider，直接写「客户端」或具体名字；"
             "定性翻身时旧措辞会散落正文各处，只改标题和开头等于没改（2026-11-11 我 6 处旧稿被用户追问才查出）；"
             "自己没复现过的能力断言要收窄（别把「一个 provider 实测」写成「协议通用规范」）",
             "发出后能一句话说清「属于哪个家族、在哪一层、和谁不重复」；发前 grep 旧定性关键词零命中"),
        ],
    },
    {
        # 2026-11-08 新增：同上。进社区之前，得先能「半小时看懂一个陌生仓库」。
        "domain": "代码考古 / 理解陌生仓库",
        "words": ("考古", "陌生仓库", "看懂", "读懂", "接手", "代码库", "仓库结构",
                  "架构", "contributing", "上游代码", "移植", "抄", "参考实现",
                  "学习项目", "别人的代码", "测绘", "调用链", "链路", "系统结构",
                  "读自己", "自己的代码", "自己的仓库", "模块边界", "数据流",
                  "读一遍", "读这个文件", "源码", "读透", "核心模块", "移植实现", "读懂实现"),
        "routes": [
            ("A", "按五层读：README → CI → 测试 → 核心模块 → issue 历史",
             "按顺序读比乱翻快得多：CI 告诉你「什么算对」，测试告诉你「什么是承诺」，"
             "issue 告诉你「最近在愁什么」",
             "要读 5 类文件，约 30-60 分钟；仓库大时要挑子目录，别全读",
             "能说出①它靠什么保证质量②它认为什么是对的③它最近在改哪块"),
            ("B", "git log --oneline -20 + git log -S <符号>",
             "看「最近在动什么」+「这行是怎么来的」；-S 能定位引入/删除某个符号的提交",
             "shallow clone 只能看近的（git fetch --deepen 可能连不上 github）",
             "能说出 3 个最近的大改动 + 1 个「为什么这么写」的来龙去脉"),
            ("C", "lab lsp（跳转定义 / 找引用）",
             "比 grep 准——能区分同名符号；大仓库里 grep 会淹死人",
             "要 pyright / 语言服务器、首次索引慢；只在支持的语言上有用",
             "能跳到定义处 + 列出引用数"),
            ("D", "读 CONTRIBUTING.md / .github/",
             "它告诉你「怎么贡献才算数」：测试怎么跑、commit message 格式、"
             "要不要 changelog——不读会白干",
             "有些仓库写得很少甚至没有；写了也可能过期（以 CI 配置为准）",
             "能背出「跑测试的命令」和「commit 格式」"),
            ("E", "先跑一遍现有测试（pytest / npm test）",
             "拿基线：知道哪些本来就在失败，别把自己引入的问题算成自己的锅"
             "（python-docx 基线 53 failed / 1547 passed / 9 errors 全是 Windows 环境问题）",
             "装依赖可能很慢；有些测试要外部服务（DB / 网络）跑不起来",
             "记下「passed / failed / errors」三个数，改完之后对比"),
            ("F", "读码三步：读核心实现 → 用自己话重写 → 差分测试证明等价",
             "2026-11-13 实测：hookable 只有 dist/index.mjs 257 行（npm 包里没有 src 也没有 tests），"
             "照着重写一份，13 条差分用例把理解漏洞逼了出来——正挂在「废弃改名链」那条我自以为懂的逻辑上；"
             "第二个对象 ofetch 349 行：20 条差分一次全绿，靠**变异验证**（故意改坏 parseResponse 与 HEAD 两处）证明用例真抓得住问题",
             "要另写一份实现和测试，2-3 小时；只适合 200-800 行的核心模块，整库重写不现实；"
             "npm 包通常不带 tests，要去 GitHub 取（api.github.com 走镜像不通，raw.githubusercontent 通，加 ghfast.top 前缀）",
             "同一套用例跑原版与重写，行为（事件序列 / 同步还是 Promise / 错误消息 / 警告次数）逐条一致"),
        ],
    },
    {
        # 2026-11-08 新增：同上。提了 PR 不等于完事，得能跟到最后。
        "domain": "长期跟踪 / 外部反馈",
        "words": ("跟踪", "后续", "反馈", "订阅", "轮询", "被拒", "拒了", "关闭",
                  "合并", "状态", "观察", "持续关注", "等一下", "过几天", "等回复"),
        "routes": [
            ("A", "gh pr status（我自己的 PR 全景）",
             "一条命令看全部自提 PR；显示「有冲突 / CI 过没过 / 待 review」",
             "要 gh 已登录；只支持 GitHub；不能看别人的",
             "能看到「有几个待处理、几个有冲突、几个等 review」"),
            ("B", "gh pr list --author @me --state all（含历史）",
             "看历史：合并了 / 被关了 / 还开着；配合 --json 能算「晾了几天」",
             "要手动看日期判断晾了多久；没有告警",
             "每个 PR 有状态 + 从提出到今天的天数"),
            ("C", "被拒原因归档成「盲区清单」（唯一能把外部反馈变成能力的动作）",
             "被拒/被晾是最贵的学习材料——别人的理由正好指出我没想到的地方；"
             "归档后下次提 PR 前能先看一遍",
             "要写，不是看一眼就完；写的时候容易写成「他不懂」，"
             "要逼自己写「我原来错在哪」",
             "E:/DS公作区/学习计划/01-编程/读码笔记/盲区清单.md 存在，"
             "每条带 PR 链接 + 被拒原因 + 我原来错在哪"),
            ("D", "定期查（每周一次，记在决策日志）",
             "不会忘；能发现「晾了三周该催一下」或「已经关了该归档」",
             "没有自动推送（除非装 gh 通知）；靠自觉，容易断",
             "每周至少查一次，决策日志里有记录"),
        ],
    },
    {
        # 2026-11-09 新增。用户 m17260：「你把这个也补入你的候选路线库里面吧，关于时间准确性的。」
        # 起因：2026-11-09 14:03 我把 11 分钟前（13:52 给的 boarding-pass 任务）说成「昨天」。
        # 根因不是不知道时间，是「昨天」在我这里是夸张词、不是日期——所以修法不是
        # 「说话前先算」（我不知道自己正在说时间），是**把这批词整批禁掉**。
        "domain": "时间 / 时长 / 时间线",
        "words": ("时间", "时长", "多久", "刚才", "上一轮", "昨天", "前天", "上周",
                  "上个月", "几个月", "隔了", "分钟前", "小时前", "几天", "日期", "时间戳"),
        "routes": [
            ("A", "lab now [--since <ISO>]（报当前时间 + 算间隔）",
             "一条命令给出「现在几点 + 距某个时刻多少分钟」，不用心算也不会算错；"
             "不带参数时顺带印〔时间〕档位行（星期几 + 现在是哪个价档）",
             "要先知道「从哪个时刻算起」——上一轮 ISO 得从前一条消息的时间戳取；"
             "跨天/跨时区仍可能漏算（它按本地时间算）",
             "输出形如「现在 2026-11-09 14:26（周一）｜距 2026-11-09 13:52 是 34 分钟前」；"
             "带 --since 时最后一行必须是「距 X 是 N 分钟前」"),
            ("B", "系统提示〔时间〕行 + identity.md 禁词条（说时间只用「刚才 / 上一轮 / 之前」）",
             "不依赖我主动想起——〔时间〕行每轮都在系统提示末尾，禁词条在 identity.md 最前面、"
             "每次会话必读；核心是把「昨天 / 前天 / 上周 / 上个月 / 几个月」整批禁掉，"
             "而不是「说话前先算」",
             "〔时间〕行只给「现在」不给「上次是多久前」，间隔仍要跑 lab now --since；"
             "禁词表是硬的，真要写日期必须当场指出出处（Get-Date / git log / 消息时间戳）",
             "同一轮里所有时间词都能落到「刚才 / 上一轮 / 之前」三选一，或带出处；"
             "出现「昨天 / 前天 / 上周 / 上个月 / 几个月」即为不合格"),
            ("C", "直接查源头（Get-Date / git log -1 --format=%ad / 文件 mtime / 消息时间戳）",
             "最硬——文件系统、git、系统时钟都不会记错；"
             "要判断「某个结论是多久前形成的」时只有源头能回答",
             "要挑对源头（git 的 author date 和 commit date 不同；文件 mtime 会被复制覆盖）；"
             "跨机器 / 跨时区要换算",
             "能指出具体命令和它的输出，例如 `git log -1 --format=%ad` → "
             "`2026-11-09 13:52:04 +0800`"),
            ("D", "lab session-age / lab steps（会话自身的时长与节奏）",
             "回答「这个会话开了多久、多少步、每步多少 token」——"
             "说「这轮花了很久」之前先拿数字",
             "只看本会话，看不到别的会话；step 数不等于轮数（一轮可能几十步）",
             "输出带「会话时长 / 步数 / 累计 token」三个数"),
        ],
    },
    {
        # 2026-11-09 新增。起因：用户报「管理员面板隔一阵闪一下」，真排查时
        # `lab pre "管理员面板隔一阵闪一下"` 的【路线】是空的——04 域「排查 / 长日志归因」
        # 只认「报错 / 日志 / 挂了」这类**长文本归因**的词，不认「闪 / 弹窗 / 谁在跑」
        # 这类**现场取证**的词。结果整场排查全手搓 PowerShell 脚本，lab 一个子命令没用上。
        # 这正是「清单里没有的，就等于我不会」的实证，所以补这个域。
        "domain": "进程 / 窗口 / 定时任务取证（谁在弹窗、谁在后台跑）",
        "words": ("闪", "弹窗", "弹出", "窗口", "进程", "计划任务", "定时任务",
                  "谁在跑", "自动打开", "自动拉起", "自启动", "提权", "管理员权限",
                  "UAC", "后台跑", "僵尸进程", "常驻"),
        "routes": [
            ("A", "Get-ScheduledTask + LastRunTime 反查（先排除计划任务）",
             "不需要抓现场——任务历史留时间戳，跑过就有记录；"
             "一条命令列出最近 N 分钟跑过的所有任务，含 RunLevel 和 LastTaskResult",
             "只能查到「任务计划程序」里的；服务/COM 代理/dllhost 的触发查不到；"
             "任务若以管理员运行而用户没开审计，可能不落历史",
             "输出形如「15:20:00 / level=Highest / res=0xC000013A / DSH-Plugin-Market-Watch」；"
             "total hit=0 就证明「不是计划任务干的」"),
            ("B", "进程轮询采样（每 2 秒对比进程表，记新出现的 pid + 父进程 + 命令行）",
             "零依赖、纯 PowerShell；能抓到存活超过 2 秒的进程；"
             "父进程和命令行是定位「谁拉起来的」的关键",
             "抓不住闪 1–2 秒的瞬时窗口（落在两次采样之间就漏）；"
             "对系统级进程 Get-CimInstance 拿不到 CommandLine（权限）",
             "日志里出现新 pid 且父进程是 svchost/explorer/userinit，就是候选；"
             "整段没有 powershell.exe/cmd.exe 就说明不是命令行脚本"),
            ("C", "WinEventHook 抓瞬时窗口（SetWinEventHook 事件驱动，不是轮询）",
             "事件驱动，窗口一出现立刻回调——1–2 秒的窗口也能抓到；"
             "能同时拿到窗口标题 + 类名 + 进程名 + pid，直接指名道姓",
             "要 Add-Type 内联 C#（P/Invoke 六个函数）；delegate 不 keep 会被 GC 回收；"
             "只在本会话跑，DSH 一关就停",
             "日志格式 `HH:mm:ss.fff <FOREGROUND|SHOW> pid=… name=… class=… title=[…]`；"
             "抓到 name=powershell title=[管理员: Windows PowerShell] 就定位了"),
            ("D", "窗口标题/类名/进程名三件套（Get-Process | ? MainWindowTitle）",
             "最快的一眼——当前所有有窗口的进程一行一个；"
             "不用挂钩子、不用等，随时可跑",
             "只能看「此刻正在显示的」窗口，闪过去的看不到；"
             "无窗口进程（后台服务）不出现",
             "输出里 `MainWindowTitle` 非空的进程就是候选；"
             "配合 `(Get-Process x).Path` 能直接给出 exe 路径"),
        ],
    },
    {
        # 2026-11-09 新增。起因：用户要接阿里云百炼的 API（300 元代金券省钱），
        # `lab pre "接入阿里云百炼 API 作为自定义 provider"` 的【路线】连续四次为空——
        # 库里没有任何一域覆盖「把一个外部模型/API 接进 DSH」。整场排查也是手搓：
        # 翻 package.json / cordis.patch.yml / .credentials.yaml、下 npm 包读源码、
        # 试 `lab asar read` 三次全失败。补这个域，把「给我 Key 就能接」写成流程。
        "domain": "接入第三方模型 / API provider（给我 Key 就能接）",
        "words": ("接入", "第三方", "API", "密钥", "Key", "provider", "baseURL",
                  "OpenAI 兼容", "兼容", "百炼", "通义", "千问", "qwen", "硅基",
                  "智谱", "OpenRouter", "换模型", "切换模型", "自定义模型", "网关", "代理",
                  "DashScope", "代金券", "窗口", "上下文窗口", "contextWindow", "413", "模型版本",
                  # 2026-11-09 补：J 路线写好之后 `lab tier "把一张图变成3D模型"` 只命中 3D 域，
                  # 第 32 域一条都没出来 —— 「条目存在但触发词对不上，等于不存在」。
                  "图生3D", "图生 3D", "图生模型", "文生3D", "文生 3D", "文生模型",
                  "Tripo", "GLB", "glb", "三维模型", "3D模型", "3D 模型",
                  "把图变成模型", "把图片变成模型", "一张图变"),
        "routes": [
            ("A", "先看现有 provider 配置点（cordis.patch.yml 的 agent-default-model）",
             "一次就看到当前 provider/model 是什么、config schema 有没有 enum"
             "（cordis_inspect_query(Config.listConfigs, entry=\"include:agent-default-model\")）；"
             "provider 是自由字符串不是枚举，理论上可填任意值",
             "只能看「配在哪」，看不出「支持哪些协议」——那要读适配器源码",
             "schema 里 provider 是 anyOf[{type:string}, loaderExpression] 且无 enum = 任意值都可填"),
            ("B", "@deepseek-ai/dsh-llm-pi-ai 多 provider 适配器 + - insert: 挂载（首选）",
             "包和依赖 @earendil-works/pi-ai 都内置于 app.asar，不用装 node_modules、不用改 bundles；"
             "手写 route 三件必填 api + baseURL + apiKeyEnv，加 models[{id, contextWindow, maxTokens}]；"
             "改完重启即生效，实测 10 分钟接通百炼",
             "要确认包里真有这个适配器（lab asar list \"pi-ai\"）；"
             "- insert: 的缩进必须手核（runtime python 没装 PyYAML，机器校验做不了）；"
             "不在 pi-ai catalog 里的 provider 必须把 api/baseURL/models 写全",
             "重启后设置页「可选用模型」出现新模型名；api: openai-completions 是 catalog.d.ts 确认的合法协议值"),
            ("C", "dsh-llm-deepseek 的 config.baseURL + $DEEPSEEK_BASE_URL（只换端点不换协议）",
             "改一行、不用加插件、不用 insert——适合「对方也讲 Anthropic Messages 协议」的场景",
             "协议写死 Anthropic Messages（/anthropic 端点 + anthropic-version header），"
             "OpenAI 兼容端点接不上；provider 名仍是 deepseek-official",
             "index.js:441 的优先级 config.baseURL > $DEEPSEEK_BASE_URL > 默认；发一条消息能回即通"),
            ("D", "Key 只进 .credentials.yaml 的 refs:（不写进 YAML、不硬编码）",
             "唯一干净入口；.credentials.yaml 不是 git 跟踪的文件；"
             "apiKeyEnv: NAME 引用的是这里的 ref 名，不是系统环境变量",
             "要改文件（备份先做）；DSH runtime python 没 PyYAML 只能纯文本改；改完必须重启",
             "refs: 段多出一行 YOUR_KEY: sk-xxx；插件侧 apiKeyEnv 写同一个名字"),
            ("E", "先核实对方协议，不要照抄别人给的模板",
             "省掉整段返工——用户粘贴的 settings.yaml + providers: + openai-completions "
             "是 Codex/Claude Code 一类工具的约定，DSH 里根本没有 settings.yaml",
             "多花 5 分钟查证",
             "ls ~/.dsh/ 没有 settings.yaml；lab asar list 里只有 dsh-llm-deepseek + dsh-llm-pi-ai 两个适配器"),
            ("F", "接进来之后按任务选模型（百炼 / 千问家族能干什么）",
             "一个 Key 覆盖七类能力，不用逐家开户："
             "**文本推理** qwen3.8-max（复杂推理与编程）/ qwen3.7-plus（均衡）/ qwen3.8-flash（快且便宜）；"
             "**视觉理解** qwen3.8-max / qwen3.7-plus / qwen3.8-omni-flash（看图、读图里的字、理解画面，"
             "可以替掉 vision_describe 的云端那一段）；"
             "**决策** decision-model-preview（一次前向完成分类 / 是非判断 / 评分，返回概率分布与置信度，"
             "比让对话模型「猜」可靠——适合给 triage 这类筛子做二次判定）；"
             "**图像** qwen-image-3.0-pro / wan2.7-image-pro；"
             "**视频** happyhorse-1.1-t2v/i2v/r2v / wan3.0-video；"
             "**3D** Tripo-H3.1 / Tripo-P1.0（文生 3D 模型，接得上 blender / Three.js 那条线）；"
             "**语音** asr-flash（听写）/ tts-plus（朗读）/ realtime-plus（实时对话）",
             "**加模型前必须查官方文档『当前版本』的窗口，别抄旧快照**——2026-11-09 实测："
             "qwen-plus 当前版本是 1,000,000 / 最大输出 32,768，"
             "而旧快照 qwen-plus-2025-01-25 才是 131,072 / 8,192，照旧快照填必然在长会话里撞 413；"
             "图像/视频/3D/语音不走 chat/completions，"
             "要各自接原生 endpoint，pi-ai 那条路只覆盖文本类；"
             "别名（qwen-plus / qwen-max）指向「当前的 plus/max」，版本会漂，"
             "要钉死版本就用带日期的号（如 qwen3.8-max-0902）",
             "文本类：把 provider 指到它、发一条消息能回即通；"
             "非文本类：curl 对应原生 endpoint 拿 200 + 产物 URL；"
             "模型名是否存在一律以 /models 返回为准，不以文档页为准"),
            ("G", "先跑 /models 核实模型名，别凭记忆或文档页写死",
             "`curl -s https://dashscope.aliyuncs.com/compatible-mode/v1/models "
             "-H \"Authorization: Bearer $KEY\"` 一次拿全表（实测 16 KB / **182 个模型**），"
             "名字存在性一目了然；同一个命令也能用来验证 Key 是否有效（HTTP 200）",
             "只给「账号能用哪些」，不给能力说明和价格；"
             "返回的是 OpenAI 兼容子集，原生 endpoint 的模型（图像/视频/3D）不一定在里面",
             "`grep -o '\"id\":\"[^\"]*\"' | grep -c` 数总数；"
             "写进配置的每个名字都先 grep 一次，命中才用——"
             "2026-11-09 实测 qwen-plus / qwen-max / qwen3.7-plus / qwen3.8-max / qwen3.8-flash 全在，"
             "而 qwen-turbo 已下架"),
            ("H", "换模型 / 长会话先算窗口：可用输入 = contextWindow − maxTokens",
             "一次算清就不会撞 413，也解释了「为什么换个模型突然就失败」——"
             "DSH 的可用输入是 contextWindow 减 maxTokens，不是 contextWindow 本身；"
             "而切换模型那一刻要把**整个上下文重发一遍**给新模型（不是只发增量），"
             "所以换模型的成本 = 当时的上下文大小，越晚换越贵（2026-11-09 实测 12.7 万 token 上下文约 ¥0.4）",
             "填错参数**不会立刻报错**，要等真跑到那个长度才 413（静默失败，可能几天后才炸）；"
             "窗口数字随模型版本变，写死在配置里就会过期；"
             "换模型那一次是「一次性大额」，攒到上下文最大时换最亏",
             "报错原文 `context ~127057 tokens ... exceeds the model window 122880 (model=qwen-plus)` "
             "——122880 + maxTokens 就是配置里的 contextWindow，一比就知道错在哪；"
             "查当前版本参数：help.aliyun.com/zh/model-studio/<模型名> 页的『当前版本』表，"
             "不查就别写数字"),
            ("I", "专用模型（图像/视频/3D）怎么调：三种端点模式 + 先看开通没开通",
             "**图像 = 同步** `POST /api/v1/services/aigc/multimodal-generation/generation`，"
             "body 是 `{\"model\",\"input\":{\"messages\":[{\"role\":\"user\",\"content\":[{\"text\":prompt}]}]},"
             "\"parameters\":{\"size\":\"2368*1728\",\"n\":1,\"prompt_extend\":true,\"watermark\":false}}`，"
             "响应取 `output.choices[0].message.content[0].image`（**URL 24 小时过期，当场下载**）——"
             "2026-11-09 实测一次成功、2368×1728 / 5.9 MB / 约 ¥0.2；"
             "**视频/3D = 异步** `POST /api/v1/services/aigc/video-generation/video-synthesis` 或 "
             "`.../3d-generation`（**3D 也挂在这个 path 下，反直觉**），必须带 header `X-DashScope-Async: enable`，"
             "拿 `output.task_id` 后轮询 `GET /api/v1/tasks/{task_id}`，"
             "视频给 `output.video_url`（24 小时）、3D 给 `output.results[0].model_url`（GLB，**只有 2 小时**）",
             "这些模型**不在 `/models`（compatible-mode）里**，只能翻文档页按能力域找；"
             "**视频/3D 要先在百炼控制台把产品『立即开通』**，否则提交后 0.3 秒就 `FAILED: "
             "The product is not activated`（账号层面的开关，我开不了，得你点）；"
             "图像模型的**文字必糊**——prompt 里写「止まれ」，出来是「全-余」这种不成词的字，"
             "要真字还得自己 CanvasTexture 画；端点写错时**三个不同模型报同一个错**"
             "（`InvalidParameter: url error`），那不是模型问题",
             "图像：HTTP 200 + `usage.image_count` 等于请求的 `n` + 落盘字节 > 0 + `read_image` 看一眼；"
             "视频/3D：先确认 `task_status != FAILED`（提交后立刻查，失败是秒级的），再等 `SUCCEEDED` 下载；"
             "两个失败特征要分清——`POST` 立刻 400 `url error` = 端点写错，"
             "`FAILED` + `product is not activated` = 没开通，别混成一类"),
            ("J", "图生 3D：一张图 → 可拖拽的 .glb（61 秒 / 50 credits），但先认清它的天花板",
             "**图片不用传图床**——`input.image` 实测**接受 base64 data URI**（文档只写「单图公网 URL」，"
             "所以第一次会以为必须找图床）。做法：`PIL` 把图缩到 1024 边长、JPEG q88"
             "（5.9 MB → 197 KB，base64 后 263 KB），拼成 `data:image/jpeg;base64,<...>` 直接塞进 body；"
             "**速度是真的快**：2026-11-09 实测便利店街角图 → 2.9 MB GLB，**61 秒 / 50 credits**"
             "（文生 3D 68 秒 / 40 credits 也一样），比建模快两个数量级；"
             "产物直接是 GLB + PBR GLB，Three.js / Blender 都能加载",
             "**单图重建有天花板，而且很低**——AI 只看到一张正面图，看不到背面、看不到玻璃后面，"
             "只能猜，猜的策略是「把看不懂的地方做成一堵墙」："
             "实测通透玻璃幕墙 + 几十排货架 → **变成一块浅米色实心墙板**、招牌文字 → 糊成色块、"
             "自动贩卖机 → 几个纸箱堆；**保住的是体量和轮廓**（屋顶围边、三色条纹、底座、护栏、电线杆、自行车）；"
             "→ **要通透/要字/要细节的任务，别指望它**，它给的是「能转的粗糙模型」；"
             "3D 产物的 URL **只有 2 小时**（比图像的 24 小时更短），当场必须下载；"
             "还要先在控制台开通，否则 0.3 秒 FAILED", 
             "`output.task_status` 必须走完 `PENDING → RUNNING → SUCCEEDED`（**PENDING 不等于成功**，"
             "上次就是先 PENDING 后 FAILED）；下载后看三个东西：`model_url` 字节数 > 0、"
             "`usage.3d_task_type` 是 `image-to-3d` 还是 `text-to-3d`、"
             "`read_image` 看一眼 `rendered_image_url` 的预览图——"
             "**预览图能立刻看出「玻璃是不是变成墙了」**，比加载模型快得多"),
            ("K", "/models/{id} 的 extra_info 是「默认部署参数」，不是模型上限（2026-11-13 差点砍掉 87% 窗口）",
             "`GET /compatible-mode/v1/models/<id>` 的 `extra_info.default_envs.max_input_tokens` 实测 "
             "qwen-plus / qwen3.8-max / qwen3.8-flash **全是 129,024**（qwen-max 才 30,720）——"
             "那是默认部署的输入上限；模型真实上下文是 1,000,000。照它写就把 1M 砍成 128K",
             "单看一个接口一定会被带偏；三个来源里有两个是「别人的默认值」而不是模型规格",
             "①官方文档『当前版本』表（help.aliyun.com/zh/model-studio/<模型名>）：上下文 1,000,000 / "
             "最大输入 991,808 / 最大输出 131,072；②大输入实测——2026-11-13 用 165,067 prompt tokens 发 "
             "qwen3.8-flash 返 200（已超 129,024，证明上限远大于它）；③`max_tokens` 边界：传 2,000,000 返 "
             "`400 Range of max_tokens should be [1, 131072]`，说明输出上限就是 131,072"),
        ],
    },
    {
        "domain": "系统建模 / 结构化理解",
        "words": ("建模", "系统建模", "领域建模", "数据流", "dfd", "c4", "上下文图",
                  "容器图", "组件图", "限界上下文", "聚合", "实体", "抽象",
                  "结构理解", "架构图", "分层", "画图", "系统结构", "测绘",
                  "系统模型", "数据模型", "领域模型"),
        "routes": [
            ("A", "C4 四层：只画到用得上为止（依据 C4 model）",
             "按受众分层，每层只答一个问题——Context「谁在用我」→ Container「我由什么组成」"
             "→ Component「组件之间怎么协作」；第 4 层（Code）不是必须的，"
             "官方明确说大多数系统停在第 3 层。一张图解决一个受众的问题，比一张包罗万象的图有用",
             "要先知道系统边界，边界错整张图都错；容易越画越像「好看的装饰」而没说清一件事；"
             "不做取舍时四层都画一遍很费时间",
             "拿 C4 官方 review checklist 逐条过：每个元素有名字/知道它的抽象层级/知道它做什么/"
             "知道技术选择；**每条箭头都有 label 写清意图**，且描述与方向一致。"
             "有一条答不出就是这张图没画完"),
            ("B", "从代码反推 DFD：先边界、后进程（依据 OLAF dfd-from-code 四阶段 12 步）",
             "有明确的阶段验证点，不靠记忆：Phase A 先确认应用类型/代码结构/配置，"
             "**Step 2 先画 Context（外部实体：用户/系统/API/数据库 + 它们之间的数据流）**，"
             "再进 Level 1（主要进程 + 数据存储），然后按复杂度判断要不要下钻 Level 2。"
             "产物是 ASCII 图，能进版本控制",
             "12 步较重，几十行的脚本用这套是杀鸡用牛刀；每阶段都要复核，赶时间时会被跳过；"
             "「进程」的粒度没有客观标准，容易一会儿太粗一会儿太细",
             "Context 图里的**每个外部实体、每条数据流都能在代码里指到对应入口**"
             "（路由 / CLI 参数 / 文件读入 / 环境变量）；指不到的那条就是猜的，删掉或标「未验证」"),
            ("C", "先定出口，再反推入口",
             "从最终产物往回推，比从头读代码快：先问「谁消费它、消费不到会怎样」，"
             "再回头看谁产生它。能立刻发现「没有消费者的数据流」——那通常就是死代码或没接上的线",
             "出口不止一个时容易只挑一个，漏掉旁路（日志、监控、告警第二条消费路径）；"
             "如果产物本身设计就错，按它反推会把错误结构固化进图里",
             "能说出「每个产物谁在读、读不到会怎样、有没有第二个读者」——三个都答得出才算看完出口"),
            ("D", "一张图只答一个问题",
             "防止「什么都画」；省时间；读者看完能直接拿到答案，不用在图里找",
             "复杂系统要画多张，容易碎片化、彼此对不上；图一多就没人维护，很快过期",
             "画之前先写下这张图要回答的那个问题；画完把图给没看过代码的人，"
             "问「这图回答了什么」——他的答案和你写的问题一致才算过"),
            ("E", "DDD 限界上下文：只在数据模型复杂时用（依据通用 DDD，非某个仓库）",
             "治「一个实体到处都在被改」：先划上下文边界，再定聚合（哪些对象必须一起改、"
             "哪些可以独立改）。边界划对了，后面的表结构和接口才稳",
             "概念重（实体 / 值对象 / 聚合 / 领域事件 / 上下文映射），小项目套上更乱；"
             "划边界需要业务知识，光看代码划不准；划错比不划更糟——会把错误的一致性边界写进代码",
             "能指出「哪几个实体必须一起改、哪几个可以独立改，理由是同一个不变量」；"
             "**构造一个反例**：如果把它们拆开各改各的，会不会出现半更新状态？会 → 边界划对了"),
        ],
    },
    {
        "domain": "DSH 界面显示 / 配置项（界面上某块不见了）",
        "words": ("界面", "看不到", "不见了", "面板", "用量", "缓存命中", "设置页", "入口",
                  "ui-chat", "ui-settings", "显示不对", "没有显示", "按钮没了", "面板没了"),
        "routes": [
            ("A", "先查 profile 的 cordis.patch.yml 里 ui-* 覆盖项",
             "每块界面都挂在某个 `@deepseek-ai/dsh-client-ui-*` 行的 config 下：`- id: ui-chat / config: {...}`、"
             "`- id: ui-settings / config: {enabled: false}`；一次就能看到「这块界面被哪个字段控制、当前值是什么」",
             "只读配置，不能证明那一块真的渲染了——配置对 + 没重启也不生效；`Config.listConfigs` 只给 schema，"
             "不给当前值（当前值在 profile 文件里）",
             "能指出「这块界面属于哪个 ui-* 行、哪个 config 字段」；指不出来就别改代码"),
            ("B", "用量/缓存命中面板 = ui-chat 的 performanceUsage",
             "`@deepseek-ai/dsh-client-ui-chat/lib/client.js:9017` 里 `detailed = usePerformanceUsage(m => m) === \"detailed\"`，"
             "`:9056` `usageAction: detailed && data.tokenUsage !== undefined ? <TurnUsagePanel/> : null`——"
             "写成 `compact` 时整块 TurnUsagePanel 不渲染（本轮用量 / 缓存命中 / 未缓存输入 / 缓存读写 / 输出全没）；"
             "取值只有 compact / detailed，默认 detailed",
             "改的是 profile 配置，必须重启才生效；且 7 个历史备份全是 detailed，说明 `compact` 是某次 profile 重写写进去的",
             "重启后那条回复底部能看到「本轮用量」面板；配置校验=js-yaml 解析出 `performanceUsage: detailed`"),
            ("C", "找不到设置入口 → 先看 ui-settings 的 enabled",
             "`- id: ui-settings / config: {enabled: false}` 会把**整个设置页**关掉，不是隐藏某一块；"
             "7 个历史备份里都是 false，是用户的长期状态，不是今天改坏的",
             "这是用户的显式选择，**不要擅自打开**；只能告知「设置页关着，所以不能在界面里自己切」",
             "profile 里 `ui-settings` 的 config.enabled 是 false = 设置页没有；改成 true 属于替用户改偏好，必须先问"),
            ("D", "改完必须冷启动才看得见",
             "client 侧 bundle 在 Boot 时读，热加载只对 HMR 生效；改 `cordis.patch.yml` 后不重启＝什么都没变",
             "交付式重启由用户按按钮（2026-11-09 分工），我只能说明「需要重启」然后停下",
             "重启后肉眼看到那一块回来（不是我读配置说「应该好了」）——用户回「看到了」才算闭环"),
        ],
    },
    {
        "domain": "会话模式 / 预设选择（Standard / PTC / ops-ptc）",
        "words": ("模式", "预设", "PTC", "ptc", "ops-ptc", "standard", "run_code", "新对话",
                  "默认模式", "forceDefaultOpsPtc", "省往返", "工具面"),
        "routes": [
            ("A", "先看当前默认是谁写的",
             "`~/.dsh/profiles/desktop/cordis.patch.yml` 的 `agent-preset-registry`（`default` / `selectedDefault`）；"
             "`Config.listConfigs(entry=\"include:agent-preset-registry\")` 看 schema。2026-11-13 实测："
             "`selectedDefault: ops-ptc` 不是用户选的，是 dsh-ops 写进去的",
             "只读配置看不出「为什么默认变了」——要读插件的 apply 逻辑才知是 `forceDefaultOpsPtc` 干的",
             "能说出「新会话默认哪个模式 + 这个值是手选还是插件强制」；说不出就是没查"),
            ("B", "Standard 与 PTC 的差别：一步一调用 vs 写程序",
             "Standard 一步一个工具调用；PTC 是模型在 `run_code` 里写 TypeScript 调 SDK——"
             "**18 个 API** = 15 个文件/文档工具 + batch + result + loader；初始只暴露 `ops_inspect_local_file` 与 "
             "`ops_load_sdk`，其余按需加载、**下一轮才生效**；省的是往返轮次，不是上下文 token",
             "每个动作要先写代码，简单任务反而更贵；代码写错整段失败（不像单工具调用只错一步）；"
             "加载的 API 当轮不能用（冻结快照）",
             "任务能用「一段程序批量做完」才选它：批量读/扫/改、循环+条件、跨多文件审计"),
            ("C", "ops-ptc 是谁给的：dsh-ops 运行时注册 + forceDefaultOpsPtc",
             "预设定义在 `dsh-ops/presets/ops-ptc.patch.yml`（源 `@deepseek-ai/dsh-web-app/presets/ptc.patch.yml`，"
             "`!!js process.platform === 'win32'` 决定 pwsh/bash），由插件 apply 时调宿主 `agentPresets.register` 注册；"
             "`global.forceDefaultOpsPtc` 默认 true，会把 `agent-preset-registry.selectedDefault` 写成 `ops-ptc`",
             "关掉开关才回官方默认；插件管理器的预设列表里**没有这条行**（它跟 dsh-ops 行同生共死）；"
             "强制值经宿主 settings 持久化，重启后仍保持",
             "关 `forceDefaultOpsPtc` 后新会话默认变回 standard；插件页 global 卡片能直接切，YAML 也行"),
            ("D", "PTC 不是免费的：先算它值不值",
             "`docs/ptc-cost.md` 实测 PTC-only 展示比 native 多 **4671 字符**提示词；官方明说「一次 batch 替代 N 次"
             "嵌套调用**不会自动省上下文 token**」，净省要靠等任务、等成功率的对比。它买的是**轮次**和"
             "**结构化错误**（`status`/`code`/`effectState`/`retry`），不是 token",
             "简单问答、单文件小改、对 SDK 不熟时用它＝先付一笔代码生成费",
             "能说出「这次为什么值得写代码」再选；只为了「看起来高级」选 PTC 就是白花钱"),
        ],
    },
]
