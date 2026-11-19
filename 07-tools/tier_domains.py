r"""候选路线库的域数据（第 0 步 · 加壳）。

从 tier.py 原样搬出来，一个字都没改 —— 拆文件时文本会变（import / 缩进 / 换行），
所以验收不看文本，看 `D:\work\.tmp\tier-baseline.py --check` 的 10 条输入
是否仍命中同样的域 / 路线 / 档位 / 组合。
"""

PATH_OPTIONS = [
    {
        "domain": "3D / 建模 / 渲染",
        "words": ("3D", "3D建模", "几何建模", "渲染", "微缩", "场景", "glb", "材质",
                  "写实", "照片级", "贴图", "纹理", "建模", "便利店", "街景", "三渲二", "cel shading", "描边",
                  "着色器", "shader", "片元着色器", "fragment shader", "体素", "voxel",
                  "风格化", "卡通渲染", "水墨", "油画", "像素风", "低多边形", "光线步进", "空气透视", "黑洞", "史瓦西",
                  "实时控制", "blender_live", "预算", "polycount", "面数", "三角形", "tri", "LOD", "纹理预算", "减面"),
            "tools": "lab blender（手写几何/厚度/倒角/渲染） / lab i23d（单图→GLB） / read_image（渲染结果肉眼验收）",
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

            # 2026-11-15 抖音 @耙耙柑（梭哈AI）WebGL 系列 1-5 集看完：海景 / 风格化 / 黑洞 / 体素江南。
            # 这四条治的是同一件事——「画面靠算不靠堆」，跟 F/G/H/J 的「建出来再修」是两个方向。
            ("P", "氛围类远景（海 / 天空 / 云 / 雾）优先写 fragment shader，不堆几何",
             "「观感来自光」的场景用解析公式在片元着色器里算，0 模型 0 贴图也能出大片感："
             "地形=分形噪声高度场、法线=中心差分、天空=Rayleigh+Mie 解析、雾=沿视线积分、海=法线扰动+菲涅尔。"
             "实测标杆：抖音 @耙耙柑《WebGL 写实海景》约 500 行 GLSL / 0 模型 / 0 贴图；"
             "黑洞那集 LIVE UNIFORMS 直接打 triangles 0 / textures 0 / 1 fragment shader。",
             "调试成本高（没有 mesh 边界，错一行整屏黑）；开销 = 像素数 × 光线步数（ray steps 64 是常见档），"
             "4K 全屏叠多层噪声会掉帧；**不擅长有明确轮廓的物体**——那种仍要建模型，别硬算。",
             "能说清画面里每个像素由哪几个函数算出来；`renderer.info.render.calls` 很小（全屏 quad 级，1–3）；"
             "把某一层（如雾）关掉能肉眼看到层次消失，说明那层确实是算出来的"),

            ("Q", "风格化渲染 = 只换着色器，不重建场景",
             "同一套几何 + 光照 + 相机，只替换 shading 代码就能出五种风格（像素 / 低多边形 / 卡通 / 油画 / 水墨）；"
             "抖音 EPISODE 3 一集演示了 5 种，LIVE UNIFORMS 打 `geometry unchanged`。"
             "做法：后处理 pass 读同一张色彩缓冲（+ 深度 / 法线），按 style uniform 分支。",
             "需要先有干净的 G-buffer（颜色 / 深度 / 法线分离）；风格化会掩盖几何细节——"
             "**所以模型可以更粗，这反而是优点**，但别指望风格化救一个烂构图。",
             "同一场景切 5 个 style 都能出画面且几何一个顶点都没动；切换只改一个 uniform，不改任何 mesh"),

            ("R", "卡通描边用 G-buffer 后处理边缘检测，不做几何描边",
             "从深度和法线突变检轮廓：`g += abs(log(c.w+1.0)-d)*6.0`（深度差）+ 法线夹角；"
             "粗细按屏幕像素统一、所有物体一致；比「沿法线外扩壳」省面数、凹角不断线。"
             "抖音 EPISODE 3 STEP 03 原话：「N·L 阶梯化为三格，阴影偏冷；G-buffer 深度/法线求边缘」。",
             "必须有 depth + normal 两张额外缓冲；多一个全屏 pass（便宜，但手机端别同时调高分辨率）；"
             "描边宽度随分辨率缩放，要按屏幕比例算、不能写死像素。",
             "近处和远处物体描边视觉粗细一致；关掉 edge pass 只剩色块、没有黑边"),

            ("S", "科学可视化把物理量直接当 shader 参数（黑洞实例）",
             "史瓦西半径直接写进 shader：`float rs=2.0*uM; float rPhoton=1.5*rs; float rIsco=3.0*rs;`"
             "（r_s=2GM/c²，量纲取 G=c=1）；质量一拖，事件视界 / 光子球 / 最内稳定轨道同步变。"
             "科普、教学类 3D 用真公式比艺术化更像真的，而且参数有意义、观众能自己查。",
             "要先查对公式和前提——史瓦西解 = 不旋转不带电黑洞，真实吸积盘要 Kerr 度规；"
             "GLSL 没有双精度，大数（10¹⁷ K 级温度）会飘；别把「渲染得像」当成「物理对」。",
             "改 M 后三个半径按 1 : 1.5 : 3 同步放大；能说出每条光环对应的物理意义，而不只是「好看」"),
            ("T", '先定预算再建模（tri 数 / 纹理分辨率 / 材质个数 / LOD 档位）',
                '预算写在建模之前，不是导完再砍。AAA 默认口径：Hero 道具 15k–50k tri、Standard 5k–15k、Background 500–5k；'
                'modular 墙（2m）200–800；Hero 角色 50k–100k、NPC 20k–40k；纹理 Hero 2048–4096 / Standard 1024–2048；'
                'LOD1 50% / LOD2 25% / LOD3 10%。**2026-11-10 雨夜街景 1544 个独立 mesh、77k 顶点就卡**——'
                '不是顶点超标，是从来没人给过「材质个数 / 合批」定预算，事后只能推翻重来',
                '数字是 AAA 默认值不是硬指标；风格化要按题材调（低模 PS1/PS2 减 50–90%、恐怖减 30–50%、风格化细节放贴图）',
                '建模前先写三行：目标 tri / 目标纹理 / 材质个数上限；交付前现数 `sum(len(o.data.polygons) for o in objs)`，'
                '超了按「删背面 → 法线烘焙 → 减 bevel 段 → 法线替几何 → LOD」的顺序处理，别一上来就减面'),
            ("U", '`tools/blender_live.py`（socket 直连**开着的** Blender，127.0.0.1:9876）',
                '改一行立刻看到结果：`code` 执行 Python、`shot` 截视口、`export` 导 GLB，命令往返 <1s（渲染另算）。'
                '2026-11-17 实测 ping 0.04s；26 个圆角方块螺旋 0.4s 建完；EEVEE 出图 12s',
                '要先有 Blender 在跑（`start` 会开 GUI 窗口，用户能看见）；`shot` 走 GPUOffScreen，首次编译着色器 20s+；'
                'addon 的 `export_scene` 参数名是 `format`（不是 `export_format`），只认 glb / fbx 小写',
                '`ping` 回 pong 且 <0.1s；改完 `shot` 的图和预期一致；`export` 的 GLB >0 B 且能被查看器打开'),
        ],
    },
    {
        "domain": "视觉 / 界面 / 截图验收",
        "words": ("截图", "界面", "预览", "视觉", "好看", "配色", "布局", "UI", "样式",
                  "动画", "入场", "过渡", "进度", "AI 味", "塑料风", "模板感", "五个指纹", "默认套路", "eyebrow", "卡片套件", "奶油底", "陶土色"),
            "tools": "desktop_screenshot（整窗） / read_image（原图细节） / lab ocr（图上小字）",
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
            ("F", "「AI 生成设计」五个指纹自检",
              "交付前对照五条，中了就说明是默认套路、不是为这个题材做的选择：①暖奶油底 #F4F1EA + 高对比衬线 + 陶土 accent #D97757（Anthropic 自家配色，最像「AI 味」）；②近黑底 + 单个酸绿/朱红 accent；③大报式细线、零圆角、密集分栏；④SaaS 卡片套件（相同圆角 + 同一软灰阴影 rgba(0,0,0,.1) + 渐变装饰）；⑤模板 chrome（标题上方全大写 eyebrow、A · B · C 中点串、WORD — fragment、#0B0B0B 冒充黑、小数据等宽、链接末尾 →）",
              "①打勾不等于错——brief 明确要求就照做，错的是「没要求时默认走这个」；②它只测「像不像套路」，不测好不好看；配「克制」用：把大胆只花在一个地方（Chanel：出门前摘掉一件配饰）",
              "交付前过一遍：哪几条中了？中的那条是 brief 要的，还是我没想？**写不出「为什么这个题材用这个」就是中了**"),
        ],
    },
    {
        "domain": "图片 / OCR / 看图理解",
        "words": ("图片", "OCR", "识图", "照片", "图里", "看这张", "截图里",
                  "识别文字", "提取文字", "文字识别", "截图里的字", "图片里的字", "这张图",
                  "看图", "读图", "扫描件", "小字", "图标", "画面内容", "图上", "图上面"),
            "tools": "read_image（直看，快） / lab ocr（版面+坐标） / vision_describe（语义理解，要联网）",
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
                  "概念图", "素材图", "AI画", "画一张", "画画", "画一个",
                  "ComfyUI", "本地生图", "本地部署生图", "Lora", "LoRA",
                  "FLUX", "flux3", "本地模型出图", "出图慢", "驱动升级", "CUDA 13",
                  "抽卡", "Stable Diffusion", "SDXL", "去水印", "无审查",
                  "放大", "更高清", "2048", "更精致", "细节不够", "不够细腻",
                  "Restore", "Lora 放大", "图太糊", "分辨率不够",
                  "精修", "锁脸", "不动脸", "不要动脸", "别动脸", "保脸",
                  "重绘", "局部重绘", "只改", "只修", "inpainting", "img2img", "图生图",
                  "触发词", "tigger word", "风格模型", "画风", "机位", "角度控制", "塔罗", "卡牌", "lab img", "出图入口", "薄封装", "工具化出图", "滑块", "slider", "滑块Lora", "双底座", "两个底座", "LCM", "ControlNet", "IP-Adapter", "IPAdapter", "控图", "姿态控制", "线稿控制", "深度图"),
            "tools": "tools/aigen（出图） / lab ocr（读生成图里的字，判断有没有错字）",
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
            ("E", "本地部署生图（ComfyUI + FLUX 3 Klein int8）",
             "**已装可用**（2026-11-16 实测）：`E:/DS公作区/ComfyUI`，FLUX 3 Klein int8 5.43 GB + "
             "Qwen3-VL-4B 文本编码器 5.0 GB + FLUX.2 VAE 0.31 GB；驱动 621.24 / torch 2.10.0+cu130；"
             "**34–38 秒/张 1024×1024（20 步）**；无水印、无审查、断网可用、可上 LoRA 锁风格；"
             "写实能力明显强于 cogview，图内文字也比 API 准",
             "首次启动 18 秒加载；显存峰值 7 GB（8 GB 卡只剩 1 GB 余量，跑着时别开别的 GPU 程序）；"
             "**驱动必须 ≥580（CUDA 13）**，否则走 eager 路径慢 10 倍（实测 7.5 分钟/张）；"
             "模型格式只认带 `comfy_quant` 的原生 int8/FP8——torchao 格式（`_type: Float8Tensor`）和 GGUF "
             "（flux3 不在 ComfyUI-GGUF 的 IMG_ARCH_LIST 里）都不认，下错白下 10 GB",
             "① 出图后量耗时，>30 秒先查 `nvidia-smi` 版本；② 下模型前读 safetensors 的 `__metadata__` "
             "有没有 `comfy_quant` 键；③ **装驱动前必须关掉占 GPU 的进程**——ComfyUI 占着会让 NVIDIA "
             "安装器静默退出、不留日志、版本不变；④ 安装器**不兼容中文路径**，先复制到 `C:/Windows/Temp` 再跑；"
             "⑤ `comfy_kitchen` 需打两处补丁（`list[int]`→`typing.List[int]` 55 处 + sage_attention 认 disabled 状态），"
             "脚本在 `E:/DS公作区/dsh-plugin-iterate/patch-comfy-kitchen.py`；"
             "⑥ **采样器用 `er_sde` + `sgm_uniform`，别用 `karras`**（2026-11-16 四组实测：er_sde 比 euler+simple "
             "快 2.4 秒且光影更好；`dpmpp_2m+karras` / `euler+karras` 两张都会把人物**幼态化**——"
             "铠甲纹理听着更多，其实是噪点能量全堆在纹理上、把脸磨成娃娃）；"
             "⑦ **要纹理别换 scheduler，加正向词**：`embossed / etched / raised relief / chased and repoussed` "
             "描述的是「凸起金属雕刻」不是「画上去的花纹」，同一组 er_sde 参数下纹路密度直接翻倍且脸不变形；"
             "⑧ CFG 从 3.5 降到 1.0 能快 41%（19.2 秒），但**画风变暗调 CG + negative prompt 完全失效**，"
             "只适合出草稿抽构图、定稿仍用 3.5"),
            ("F", "tools/comfy_upscale.py（Restore LoRA 放大重绘）",
             "**2026-11-16 实测**：1024 出图后放大到 2048，用 Restore LoRA 重绘补细节，"
             "`denoise 0.40` + 8 步 CFG 1，**46-57 秒**出一张 5.2 MB 的 2048；"
             "实测细节量明显增加（铠甲金丝纹、头发丝、项链），而脸/姿势/构图全保。"
             "**完整流程 用 92 秒出一张 2048**（1024 生成 35s + 放大 57s），比 MJ 排队快、免费本地",
             "**denoise 是关键旋钮，0.45 是红线**：0.40 保脸；0.55 眼睛变色、五官偏移、"
             "**女性角色开始男性化**（用户 2026-11-16 原话「剩下两张看起来男性风格过重」）；"
             "0.70 直接换人（金瞳、硬朗脸型）。工具默认 0.40，传 >0.45 会打警告但不禁用。"
             "另：Restore 是**图生图**专用，塞进纯文生图流程里几乎看不出效果（试过，四个配置里最没用的就是它）",
             "① 放大的图必须和原图并排看，确认「同一个人」而不是「同一题材」；"
             "② denoise 改大后重点看**性别特征**——这是最先漂移的地方；"
             "③ 源图要先复制到 `ComfyUI/input/`（LoadImage 只读这个目录，不读 output）"),
            ("G", "tools/comfy_refine.py（MediaPipe 锁脸的局部重绘）",
             "**2026-11-16 建成，用户原话「精修就只是精修它的细节，不要过多对于面部的变化，除非有我明确的指令」**。"
             "流程：`MediaPipeFaceLandmarker` 检测脸 → `MediaPipeFaceMask` 出 mask → `GrowMask` 外扩 24px → "
             "`InvertMask` → `InpaintModelConditioning` 只在非脸区域加噪 → 采样。"
             "**脸区域根本不参与采样**，denoise 开到 0.65 也动不了它；头发/脖子/光影是同一次渲染出来的，**没有接缝**。"
             "36 秒/张，默认 `--expand 24`",
             "**别用后处理贴脸**（PIL 椭圆遮罩把原图脸贴回去）：羽化 24 有硬边、羽化 48 变糊边，"
             "因为头发丝/脖子阴影/耳环反光两侧不是同一次渲染，**接缝消不掉**——这是「事后合成 vs 模型内遮蔽」的本质差别。"
             "另：MediaPipe 对动漫脸**不是 100% 命中**（Q 版/侧脸/遮挡会失败），失败时 mask 为空等于不保护，"
             "所以默认开了兜底：检测失败自动退回 `comfy_img2img.py --protect-face` 并打印警告，"
             "`--no-fallback` 可关掉",
             "① 图里必须有明确的人脸，检测占比 <0.5% 就当失败；② 锁脸后**脸必须和原图逐像素一致**"
             "（对比眼角、耳环位置）；③ 别拿它当放大工具——放大用 F 条 `comfy_upscale.py`；"
             "④ 检测模型 `mediapipe_face_fp32.safetensors`（5.42 MB）放 `ComfyUI/models/detection/`，"
             "`/object_info/LoadMediaPipeFaceLandmarker` 的 `model_name` 选项里能看到才算装好"),
            ("H", "`ComfyUI/models/loras/` + `_索引.md`（Lora 加风格/控制）",
             "**2026-11-16 晚建立，用户「至少不用自己摸索啊」**。"
             "Lora = 给底座打补丁，**不用在 prompt 里描述风格细节，它自己带**（塔罗 Lora 连金边框和四角星盘都是自动出来的）。"
             "加载节点 `LoraLoaderModelOnly`（只改模型不改 CLIP）。索引表 `E:\\DS公作区\\ComfyUI\\models\\loras\\_索引.md` "
             "记了每个 Lora 的触发词/推荐强度/效果评价。现有：tarot（0.85，塔罗牌框）、angles（0.80，机位控制）、"
             "restore（1.0，放大用）、consistency（0.8，跨 seed 保脸）",
             "**Lora 是模型专属的**：FLUX 3 Klein 的 Lora 只能配 FLUX 3 Klein，SDXL/SD1.5/FLUX.1 的全都不通用。"
             "判断方法：HuggingFace 页面看 `base_model:` 标签，或读 safetensors 的 `metadata()['ss_base_model_version']`。"
             "触发词在 `ss_tag_frequency` 里（kohya/ai-toolkit 训练的都写进去了），"
             "**有了必须写进 prompt 才生效**。强度 **>1.0 会盖掉原画风**；风格类 0.7–0.85、控制类 0.6–0.8。"
             "格式上 diffusers（key 前缀 `transformer.`）和 kohya（`diffusion_model.`）ComfyUI 都能直接读，不用转换",
             "① 下完必须验完整性：`safe_open` 抽 tensor 看 `mean(|w|) > 0`，**516 keys 是 FLUX 3 Klein Lora 的正常值**"
             "（比这个少或权重全 0 = 文件下坏了/稀疏空洞）；② 测试时**同 seed 只换 Lora** 才看得出差异；"
             "③ 用户不喜欢油画风（Hammershoi 已删），推荐风格 Lora 前先想他的审美：偏插画/动漫，不要厚涂油画；"
             "④ 新 Lora 放 `ComfyUI/models/loras/` 后**不用重启**，ComfyUI 每次请求重扫目录，"
             "查 `/object_info/LoraLoader` 的 `lora_name` 选项确认识别"),
            ("I", "`tools/comfy_lora.py`（用 Lora 出图，命令行工具，可叠加）",
             "**2026-11-16 晚建成，把「改 test_lora_style.py 里的配置手跑」升级成正式工具**。"
             "`python comfy_lora.py --list` 看本地有哪些；`python comfy_lora.py \"prompt\" --lora tarot` 单个；"
             "`--lora tarot:0.85 --lora restore:1.0` 叠加（串成 `LoraLoaderModelOnly` 链）；"
             "`--draft` 走 cfg 1.0 草稿档（19 秒）。Lora 名字**模糊匹配**：写 `tarot` 能匹配 "
             "`flux3-tarot-lora.safetensors`",
             "**Lora 开了一定出效果是个错觉**——实测同 prompt 同 seed 下，`lora_tarot` 出了金色牌框，"
             "而 `test_lora_tool`（prompt 里只写了一句 `tarot card illustration`）**没出牌框**，"
             "说明 Lora 的引导需要 prompt 配合：要牌框就写 `tarot card, ornate border frame, four corner emblems`。"
             "另两个代价：①模糊匹配撞名会直接报错并列候选（这是故意的，防止拿错 Lora）；"
             "②强度 >1.0 会盖掉原画风、≤0 等于没开（工具会给警告）",
             "① `--list` 应列 4 个（tarot / angles / restore / consistency）；"
             "② 叠加时看 `Lora` 那行打印的顺序和强度对不对；"
             "③ **判断 Lora 有没有生效，必须同 seed 同 prompt 对比「开」与「不开」两张**，"
             "单看一张分不出是 Lora 的功劳还是 prompt 的功劳"),
            ("J", "`lab img`（一个入口收五个生图脚本的薄封装）",
             "**2026-11-17 建成。治的不是「能不能用」，是「我记不记得有它」**——"
             "五个脚本散在 `tools/` 目录里，每条命令一套参数一套默认值，写回忆录时才发现 comfy_lora.py 建好了却没进清单。"
             "现在 `lab img` 一个 `--help` 看全：`status`（服务在没在跑 + 显存温度）／`serve [--stop] [--background]`／"
             "`gen`（--lora 可叠加）／`i2i`（图生图）／`up`（放大 2048）／`refine`（锁脸精修）／`text`（加字条）／`list`（本地 Lora）。"
             "**只做参数映射 + 转发，底层脚本保留可单独调**；每次调用进 `~/.dsh/lab-calls.log`，两周后 `lab tools` 能看出哪个动作从没被用过",
             "**转发型薄封装的代价是它不理解底层**：底层脚本改了参数名/默认值，这里要跟着改，不会自己报错；"
             "`serve --background` **必须 `Popen(... stdout=DEVNULL, stderr=DEVNULL)`**——用 `subprocess.run` 等 powershell 退出会让调用方永远等，"
             "因为 ComfyUI 子进程继承了管道（Windows 上后台进程继承父进程句柄的经典坑）；"
             "`start-comfy.ps1` 里**绝不能调 `comfy_kitchen.disable_backend(\"cuda\")`**——torch 加载后再改分配器后端触发 "
             "`cudaMallocAsync != native` 的 CUDAAllocatorConfig 断言，ComfyUI 直接起不来（这条记忆早就写着，是脚本没跟上）",
             "① `lab img --help` 应列 8 个动作；② `lab img serve --background` 应 **19 秒内返回**（不是卡住）；"
             "③ `lab img gen \"prompt\" --lora tarot:0.85 --seed 42001 --prefix e2e` 应 38 秒出图且**带塔罗金色牌框**；"
             "④ `lab img status` 出图后应显示显存占用与温度"),
            ("K", "tools/comfy_sdxl.py（SDXL 底座 + 滑块 Lora，与 FLUX 并列的第二条路）",
             "**2026-11-17 建成**。`python comfy_sdxl.py \"prompt\" --lora anime:2.0 --cfg 5`。SDXL 1.0（6.5 GB / 2.6B UNet）比 FLUX 3 Klein（5.6B）**快约 20%、显存少一半**，生态大得多（社区 Lora 几万个）。配 8 个 ntc-ai 滑块（各 8.4 MB，`-3~+3` 连续可调）：cinematic-lighting / extremely-detailed / nice-hands / pixel-art / ghibli / pixar / dynamic-anatomy / anime，外加 chinese-ink（水墨）和 watercolor（水彩）两个整装 Lora。**2026-11-17 补了加速与控图**：`--lcm` 挂 LCM 加速 Lora（375.6 MB，默认 6 步 CFG 1.5）；`--cn-image 图 --cn-type canny/depth/pose/lineart/tile` 走 ControlNet Union promax（2,396.9 MB，可带强度 `pose:0.9`，tile 实测 46.3 秒）",
             "**滑块有三条跟普通 Lora 完全不同的规矩**：①**触发词必须写进 prompt**——`anime:2.0` 不写 `anime` 出来还是写实 CG（我白跑两张才确认）；②强度范围 **-3~+3** 不是 0~1，滑块用 1.5~2.5；③**CFG 决定能推多远**：7 几乎看不出、5 温和过渡、3 很强但会跑偏（anime 给角色头上加了角），官方示例 CFG 2、推荐 4~5。另三条坑：bf16 的 Lora 要用 `safetensors.torch.load_file`（numpy 版报 `bfloat16 not understood`）；HF API 的 `usedStorage` 包含 images 目录（报 43 MB 实际 8.4 MB）；风格滑块**不带 text_encoder**，`LoraLoader` 会自动忽略 clip 那半。短板：写实人像不如 FLUX 细腻，画质上限低一档。**控图两个限制**：①`--cn-image` 传的必须是**已经处理好的 hint 图**（边缘/深度/骨架），因为 ComfyUI 核心没有 `Canny` 节点（要装 `comfyui_controlnet_aux`），只有 `tile` 能直接喂原图；②**IP-Adapter 用不了**——`/object_info` 里 `IPAdapterUnifiedLoader`/`IPAdapter` 一个都没有，要装 `ComfyUI_IPAdapter_plus` + CLIP Vision（约 2.5 GB），且下载来的 144 键里 133 个是零、是否官方如此未实测；③ControlNet 的层前缀是 **`controlnet_cond_embedding`** 不是 `controlnet_conditioning_embedding`（按错名字查会误判成没有）",
             "① `comfy_sdxl.py --list` 应列 15 个 Lora（4 FLUX + 8 滑块 + 水墨 + 水彩 + LCM）并列出 ControlNet 目录里的 promax；② 1024×1024 / 30 步 / CFG 7 应 **26~32 秒**（带 ControlNet 46 秒）；③ 滑块生效判据是**同 seed 对比开与不开**，单看一张分不出是 Lora 还是 prompt 的功劳；④ CFG 压低后重点看有没有跑偏（多出来的角、畸变）；⑤ `--lcm` 出图应 **6 步 CFG 1.5**，`--cn-image ... --cn-type tile` 应保持参考图构图"),
        ],
    },
    {
        "domain": "排查 / 长日志归因",
        "words": ("报错", "日志", "排查", "归因", "为什么", "挂了", "失败", "异常",
                     "能变红的回路", "复现脚本", "先建回路", "反馈回路", "最小复现",
                     "猜", "推测", "凭印象", "没验证", "别猜", "硬证据"),
            "tools": "lab errors（报错原文聚合） / triage.py+3b（长日志先筛） / read（截上下文）",
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
            ("F", "诊断前先建「能变红的紧回路」（一条命令，驱动真实 bug 路径、断言用户描述的确切症状）",
             "有了能变红的信号，二分/假设测试/打点都只是消费它；没有的话盯代码多久都救不了。"
             "2026-11-17 修 lab img serve 卡住，连猜三轮（管道继承→参数被拆→disable_backend）才中，根因就是没先建这条命令",
             "建回路本身要花时间，简单 bug 会显得慢；回路不紧（30 秒且 flaky）几乎等于没有——要压到秒级并钉住随机源（时间/随机数/网络/文件系统）",
             "能说出「一条命令」且已跑过一次、它能在 bug 上变红：四条打勾 = 能变红 / 确定性 / 秒级 / agent 无人值守可跑。"
             "建不出回路时停下来说清试过什么，别进入猜根因"),
            ("G", "说「因为 X」「根因是 X」之前，先指出读过的行号 / 跑过的命令 / 看过的日志；指不出来就说「还没查」或「我猜是 X，还没验证」",
             "把「猜」和「查」在措辞上分开。2026-11-18 排查 dsh-evolve 时我猜两次"
             "（①1.9 MB 的 inbox 文件被整个塞进 headless ②修法是截断），两次都被随后读的 "
             "scan.ps1:42 推翻——真正的重是 prompt 要求了五步任务；同一天用户点破"
             "「你是不是为了方便才拆的…不能猜，以后做任务的时候不能猜哦」",
             "会慢一点：读代码要定位+读+比对+说清在哪一行，猜只要一句话；而且**猜中之后没人会问"
             "「你怎么知道的」——猜本身不留痕迹**，所以更容易退回去",
             "报告里每个「因为 / 根因是」后面能指认三条之一：`文件:行号`、`命令 + 输出`、`日志行`。"
             "指不出来就用「我猜是…还没验证」开头——**「我猜是」三个字必须说出来**，不能把猜包装成结论；"
             "反过来也别把「已经查到的」说成「我猜」来免责"),
        ],
    },
    {
        "domain": "推理档位 / 思考深度",
        "words": ("推理档位", "降档", "升档", "思考深度", "想得浅", "这么浅", "reasoning", "thinking level", "草率"),
            "tools": "lab tier（任务复杂度） / config（模型档位）",
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
        "words": ("插件", "deploy", "安装", "卸载", "profile", "cordis", "bundle", "升级", "市场", "社区", "dshmarket", "mcp", "skill", "技能", "插件索引", "现成的", "第三方", "cli", "命令行工具", "可执行文件", "版本", "新版本", "更新", "要不要升", "可选依赖", "ModuleNotFoundError", "import 失败", "try except import", "第三方包改不动"),
            "tools": "lab vet（装前扫权限） / lab deploy（改完生效） / lab selfcheck（版本漂移看第 17 组） / env_doctor（坏了查）",
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
            ("Q", "第三方插件自带 CLI：状态页说 available ≠ 能 spawn（2026-11-13 agentero 实测；该插件已于同日卸载，案例留作方法）",
             "①读插件源码确认它 spawn 的到底是哪个字符串（`runAgentero(settings.agenteroBin)` 的默认值就是裸 `agentero`，**不会**回落到它自己识别到的 managed 二进制——`source: managed` 只用于状态页显示）；②把可执行文件放进**本来就已在宿主 PATH 里**的目录（本机 `C:\\Users\\<user>\\.local\\bin`），立刻生效、不用重启；③验证要直接调那个工具，不看状态页",
             "改注册表 PATH 对运行中的宿主进程无效（env 在启动那一刻固化）；拷一份 exe 会多占磁盘（agentero 33 MB）",
             "调一次该工具（如 `agentero_list_papers`）返正常 JSON 才算通；available/version 只算旁证"),
            ("R", "第三方包被「可选依赖」卡死 import：grep 用法后打 try/except，别为它装几百 MB（2026-11-17 实测）",
             "scrapling 0.5.1 的 `engines/toolbelt/convertor.py:7-9` 在**模块顶部**硬 `from patchright.sync_api import ...`，没装 patchright（Playwright 的隐身分支，带浏览器二进制）时连纯 HTTP 的 `Fetcher` 都 import 不了。grep 全部 15 处用法发现**只有类型标注和 `except PatchrightError`、没有一处 isinstance** → 包进 `try/except ImportError` 用占位类（`SyncPage = AsyncPage = object`），`Fetcher` 立刻可用，`StealthyFetcher` 仍如实报 ImportError 而不是静默降级",
             "改的是第三方包内部文件，升级会被覆盖 → 改前备份 `.bak-<理由>`、记下改的行号；如果真需要被跳过的那部分功能（如过 Cloudflare），还是得装它，补丁只是解除阻塞不是替代",
             "被卡住的那个 import 能通 + 原本能用的部分（`Fetcher.get` 返回 200）不受影响 + 跳过的部分调用时抛明确错误"),
            ("S", "版本号漂移：改完插件先跑 `lab selfcheck` 第 17 组，别靠「我记得改了」（2026-11-18 建）",
             "三条判据机器验：①`CHANGELOG.md` 最新标题版本 ≠ `package.json.version` → **硬错误**；"
             "②`lib/` 最新 mtime 比 `package.json` 新超 1 天 → 提示（改了代码没升版本）；"
             "③自研插件没有 `CHANGELOG.md` → 提示。**起因**：用户 2026-11-18 指出「以前每次插件更新，"
             "多多少少都会版本型号没更新过来，不止一回了」——本域 D 条的判据早就写着「版本号和 "
             "package.json 对得上」，但**那只是一句给人读的话，没有任何工具去验它**。"
             "同一天实测抓到两个真漏：`dsh-stickers` 0.1.3 没升到 0.2.0、`dsh-memory` 代码比 pkg 新 4 天",
             "只查「CHANGELOG 与 package.json 对不对得上」，**查不出「代码改了但两个文件都没改」**；"
             "mtime 判据会误报（只改注释也算新）；`SELF_BUILT` 之外的插件不查；"
             "版本号该升到多少仍需人判断（它是语义不是算术）",
             "`lab selfcheck --only 17` 输出 0 处不一致；**自我测试**：故意把某个 CHANGELOG 的版本数字改错，"
             "这一组必须报出来（不报说明判据失效）"),
        ],
    },
    {
        "domain": "DSH 升级 / 安装器 / 版本回退",
        "words": ("升级 DSH", "更新 DSH", "点更新", "安装器", "NSIS", "卸载记录",
                  "找不到安装路径", "不会自动启动", "更新完", "profile 被重写",
                  "patch 丢了", "更新后报错", "安装位置", "新版本发布", "左下角更新",
                  "nightly", "release 通道", "安装包", "每回更新", "回回更新", "自愈", "selfheal",
                  "patch 漂移", "更新太麻烦",
                  # 2026-11-15 补：只加 routes 不加 words，新路线永远命不中（当天实测教训）。
                  "第三方插件", "npm 升级", "升级覆盖", "被覆盖", "覆盖我的改动", "本地补丁",
                  "补丁脚本", "接管更新", "整目录替换", "升级后我的修改", "更新完", "升级完", "同步三处", "同步六面", "版本号", "文档同步", "更新之后", "索引表", "索引没改", "决策日志", "回写", "状态同步", "同步一下状态", "同步状态", "同步一下", "自身状态", "哪些面", "漏了哪面", "同步哪些", "同步完了吗"),
            "tools": "update-dsh.ps1 / rollback-dsh.ps1 / patch-audit.mjs",
        "routes": [
            ("A", "升级前：update-dsh.ps1 -DryRun",
             "先看清会装什么、会不会动插件清单；脚本自己校验 SHA512、备份 profile 三件、备份整个安装目录当回滚点",
             "必须在 DSH 外跑（脚本会关掉 DSH，当前对话会断）",
             "DryRun 输出：安装目录 / 当前版本 / 待装版本 / 需关进程数"),
            ("B", "升级后第一件事：patch-audit.mjs",
             "对比基线 `E:\\DS公作区\\备份\\patch-baseline.yml` 与当前 `cordis.patch.yml`，直接报 MISSING / changed",
             "基线太旧会报假漂移；config 值变化只提示不自动改",
             "`RESULT: OK` 才算过，否则进 C"),
            ("C", "有漂移：patch-restore.mjs（先 --dry-run）",
             "只补基线有、当前缺的条目，已有条目一个字节不动，写前自动备份，重复跑幂等",
             "只补不删；条目在但 config 变了它不管，要人判断",
             "`RESULT: RESTORED` → 再跑一次 patch-audit 应 OK"),
            ("D", "更新后坏了：rollback-dsh.ps1",
             "整个安装目录回滚到备份点，并还原 `cordis.patch.yml` / `package.json`",
             "备份点只留最近 2 份；会话/记忆数据不在备份里",
             "`rollback-dsh.ps1 -List` 能看到备份点与版本"),
            ("E", "手动打开旧版（不用脚本）",
             "先关当前 DSH，再双击 `备份\\dsh-update\\<stamp>\\install\\DeepSeek Harness.exe`",
             "不要和当前版本同时开，会抢同一个 profile 目录",
             "窗口关于页显示的是备份那版的版本号"),
            ("F", "安装器找不到路径：查僵尸卸载记录",
             "NSIS 的 `--updated` 分支按注册表 Uninstall 的 `$INSTDIR` 决定装到哪；指向不存在目录的旧记录会让它走错（2026-11-14 实测根因）",
             "只删 exe 不存在且 InstallLocation 也对不上的那条；删前 reg export 备份",
             "`Get-ItemProperty HKCU:...\\Uninstall\\*` 里只剩一条且那条的 exe 存在"),
            ("G", "更新完不想每次都重修：selfheal.ps1（自愈）",
             "`patch-audit` 发现 MISSING 才 `patch-restore`，config 值差异只报告不覆盖（那多半是自己在界面改的）；"
             "日志 `reports\\selfheal-log.txt` 只看 `[ACTION]` 行。已挂计划任务 `DSH-SelfHeal`（登录后 5 分钟）+ `DSH-SelfHeal-Daily`（12:30）",
             "计划任务按 Windows 登录/定时触发，**DSH 重启不触发**——更新完立刻自愈还得靠 update-dsh.ps1 里的那次 audit",
             "`selfheal.ps1 -DryRun` 跑完 exit 0，日志里出现 `[OK] patch 配置与基线一致`"),
            ("H", "npm 装的第三方插件，本地改动升级即失——必须建幂等补丁脚本（2026-11-15 bili 实测）",
             "`billion-context` 在 profile 是 `\"0.1.213\"`（非 `link:`），`(Get-Item).LinkType` 为空 → npm 整目录安装 → "
             "升级把 `node_modules/billion-context` 整个替换，dist 里的改动全没。做法：只改纯函数 → `node --check` → "
             "写幂等脚本（`--check` 判 patched/unpatched/partial、`--dry-run` 预演、自动备份、语法失败自动回滚、`--target` 换路径）→ "
             "写进升级流程文档（ITERATE.md）→ 每次升级后重跑",
             "OLD/NEW 是逐字匹配，上游改结构就失效（`--check` 报 partial，要按新代码重写）；脚本本身也要维护",
             "`patch-bili.mjs --check` exit 0（patched）；升级后重跑一次仍 exit 0；`node --check <dist>` exit 0"),
            ("I", "第三方插件有新版本：由我接管更新，不点界面更新（2026-11-15 用户定）",
             "用户原话「这个插件就由你来接管，由你来更新……每当有新的更新我就告诉你，让你去读它所更新内容」；"
             "原因是 npm 升级会覆盖本地补丁。五步：①查版本 ②下载 tarball 到 `.tmp\\bili-<ver>\\` ③读 CHANGELOG + diff 新旧 dist，"
             "**先判断 upstream 是否已修**（已修就不打补丁）④`patch-bili.mjs --target <新版dist>` ⑤备份替换 → 用户重启 → "
             "看 `bili.log` 的 `nudge usage=` 与 `request ... inbound=` 是否量级对上",
             "每轮要下载 + 读 diff，约 5–10 分钟；upstream 大改时 OLD 文本失效要重写补丁",
             "`patch-bili.mjs --check` exit 0；bili.log 里 `[acp-usage] input=` 与 `inbound` 同量级；出问题用 `备份\\bili-dist-index.js.bak-<日期>` 回滚"),
            ("J", "一次更新多个插件：先分流来源，再按「对我有没有用」逐个定",
             "查 profile package.json 把 21 个插件分三类——npm 版本号 / link: 本地源码 / file: 本地打包；只有 npm 类有「更新」概念。对 npm 类查 registry 最新版（npmmirror 不行换 registry.npmjs.org），命中差异的再读 release notes 判断「对我有没有用」，不盲目追新（2026-11-16 实测 4 个可更、只升 3 个）",
             "18 个包要查两轮（镜像 + 官方）；npm 上有同名包污染（dsh-memory 报 0.1.0 而实际是 0.6.17），要核对 repository 字段才敢信；link/file 包没有「更新」一说，改源码即生效",
             "本地版本与 registry 最新版并排打印（`npm view <pkg> version` + package.json）；升完验进程启动时间晚于包 package.json 修改时间 + `env_doctor only=health` 0 待生效"),
            ("K", "任何东西更新完（插件/DSH/配置/自研工具链）都要同步六面，不是更新完就结束",
             "（收尾段路线：不是开工时查，是干完「更新」这件事之后反过来查。开工时看到它别当成事前准备。）更新改变的是「世界」，别处写的是「旧世界」。**六面逐项过，每面记法不同**：①记忆库：新知识用 memory_save，**旧条目里的数字/版本号/清单必须同步改**（数字是最容易烂的，同一事实存两份就等于存了一份错的）②候选路线库：tier_domains.py 加路线**或**补 words（只加 routes 不补 words 永远命不中），改完 lab test + 重建基线 ③机制文档：我的能力清单.md / 外来插件掌控表.md / 机制总图对应层 ④**索引台账**：_索引.md 这类「人找得到」的表（它不属于机制文档，最容易漏——2026-11-17 就被用户点破只改了记忆没改 _索引.md）⑤决策日志：lab log --mark + --body-file，记「为什么」不只记「做了什么」⑥回写：lab tier --used 域/代号 --note，没有改变做法也要写 none。**另有一条边界**：ComfyUI/models/ 这类被 .gitignore 排除的，git status 看不见，同步完要单独确认「它不在 git 里」这件事本身写没写下来。2026-11-16 升级三个插件、11-17 加 SDXL 控图各实测走了一遍",
             "六面逐项过要 15–25 分钟，比三面贵；但漏一面的代价是「下次用旧结论」——而且 selfcheck 查不出索引表过期、版本号漂移、记忆里的旧数字，只有逐面点名才拆得掉。2026-11-17 两次漏面都是这个原因：改完代码只改了记忆，_索引.md 和旧记忆里的「14 个」都是用户问才发现的",
             "`git log --oneline -5` 能看到记忆/路线库/文档各自有提交；`lab selfcheck` 0 漂移；`grep -r \"<新版本号>\" 架构文档` 有命中；记忆里的版本号与 `node_modules/<pkg>/package.json` 一致"),
        ],
    },
    {
        "domain": "写代码 / 改代码",
        "words": ("写代码", "改代码", "实现", "重构", "函数", "脚本", "修 bug",
                  "新特性", "加特性", "补丁", "旧代码", "遗留", "赋值", "循环条件", "while",
                  # 2026-11-15 补：新路线 K（改 minified bundle）与 L（评估改第三方风险）的触发词。
                  "minified", "bundle", "打包后", "混淆", "第三方代码", "改第三方", "风险", "白名单", "内存泄漏", "改文件", "编辑文件", "锚点", "old_string", "匹配失败", "找不到匹配", "改坏了", "语法坏了", "hashline", "精确匹配",
                  # 2026-11-17 补：路线 O（校验器漏检）的触发词。
                  "自检查器", "校验器", "漏检", "误报", "静态扫描", "注册方式", "检测不到",
                  "assert", "-O", "优化模式", "校验被移除", "静默失效"),
            "tools": "edit/write（动手） / lab lsp（定位符号） / lab test（回归）",
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
            ("R", "插件「有新版」先判版本语义，再决定升不升",
             "`plugin_manager` 比的是字符串不是 semver：rc.1 比 latest 的 alpha.2 新、registry 的 latest 有时指向旧版——直接升等于降级",
             "要读三个版本号（已装 / registry latest / 实际最新 tag），约 30 秒",
             "2026-11-13 实测 23 个：只有 dshmarket 1.70.2→1.73.19 该升；forge-bundle 已装 0.2.2-rc.1 vs latest 0.2.2-alpha.2（rc 更新，不升）；subagent-claude-code 已装 0.2.1-rc.3 vs latest 0.0.1-rc.1（latest 指向旧版，不升）"),
            ("K", "改 minified / 打包后的第三方 bundle：四步最小风险法（2026-11-15 bili 实测）",
             "①先按函数名定位（`indexOf('function xxx(')` 或 grep），再截前后几百字符读——**不要整文件读 6MB 单行**；"
             "②只改纯函数（输入→输出，无网络/无状态/无异步），不碰事件循环里的东西；③改前 copy 备份原文件，改后 `node --check`（ESM 用 `--check`）；"
             "④写一个新旧行为对比的小测试（如模拟 1154 条消息：旧 418,278 vs 新 435,339）",
             "打包后变量名被压缩（`m2`/`s3`），改错一行不报错但语义偏；没有 sourcemap 只能靠上下文推断",
             "三样证据齐才算改对：语法 exit 0 + 行为对比有差异且方向对 + 幂等脚本 `--check` 报 patched；少一样都只是「看起来改了」"),
            ("L", "评估「改第三方」风险：拆三层，别用「风险大」一句话挡住（2026-11-15 用户 m03227 逼出来）",
             "用户问「是怎样一个风险法？你控制不了吗？不能降下去吗？还是你的能力做不到？」——三层分开答："
             "①**风险是什么**（具体到文件/函数/最坏后果，不是形容词）②**能不能降**（备份 + 语法检查 + 幂等 + 回滚路径，每条对应一个失败模式）"
             "③**是不是能力问题**（能不能在打包代码里定位到纯函数）。三层都能说清 → 风险可控，该做；说不清 → 才是真风险",
             "拆三层要多花几分钟；拆完仍可能发现最坏情况不可逆（改的是加密/签名/数据迁移逻辑）——那时才该停",
             "能逐条说出「最坏情况 + 怎么回到原样 + 哪步能提前发现错」；三条有一条答不出来就先别动"),
            ("M", "改文件的三个动作：稳定标识定位 → 改前查陈旧 → 改后验解析（2026-11-16 从 oh-my-pi 的 hashline 吸收）",
             "三件事各治一种失败：①定位用「函数名 + 一小段上下文」或「域+代号」这类稳定标识，不把整段旧代码抄进 old_string（抄越长越容易差一个全角引号或缩进——2026-11-15/16 两次锚点失败都是这个）；②改前确认文件没被动过（DSH 的 ops_edit_file 有 expectedRevision 可做 CAS，自研文件看 mtime）；③改完立刻验「还能不能解析」——.py 跑 py_compile、.js 跑 node --check、.json 跑 json.loads，不验等于没改完",
             "多点两步；锚点太短会歧义（要带足够上下文）；校验只能证明「语法没坏」，证明不了「逻辑对」",
             "改前 grep 出定位串 → 改后 py_compile/node --check 输出 OK → git diff --stat 行数只动了目标行"),
            ("N", "重要改动让「第二个模型」复审——自己审自己有盲区（2026-11-16 建）",
             "把 diff + 验收标准交给独立 subagent，**不告诉它我的推理和结论**，只让它回答：这段改动有没有破坏原有行为 / 边界条件漏了没 / 和验收标准对得上吗。同模型也行，关键是它没看过我的思考过程，只看结果",
             "多一次调用成本；它可能挑出无关紧要的；只让它指出问题、不许它改代码（改了就变成两个黑箱）",
             "它明确报出 1-3 个具体问题（不是「看起来没问题」）才算有效；连续两次答「没问题」而后续真出 bug → 这个审核是假的，换更严的验收标准"),
            ("O", "校验器/自检查器本身会漏检——先问它怎么发现对象",
             "能发现「文档写了但实际没有」这类漂移；前提是它的探测方式和真实注册方式一致。"
             "2026-11-17 修 selfcheck 时验证：把探测改成运行时取 `build_parser()._actions` 后，"
             "子命令数全部对上，0 漂移",
             "静态扫描（正则扫源码）在对象改用**外部模块 register(sub) / 装饰器 / 运行时拼接**注册后会"
             "**静默漏检**，报的是假阳性——看起来有漂移，实际是检测器看不见。"
             "`selfcheck.lab_subcommands()` 原来只扫 `lab.py` 里的 `sub.add_parser(...)`，"
             "而 `lab img` 在 `img.py` 的 `register(sub)` 里注册 → 数出 48 个、还误判「文档写了 lab img 但不存在」",
             "先问「这个检查器怎么发现对象的」：①扫源码 → 对象可能是动态注册的就有风险；"
             "②跑一次运行时对比（`build_parser()._actions` 找 `_SubParsersAction.choices` / `inspect` / 直接 `--help`）；"
             "③两边不一致时以运行时为准，改检查器而不是改文档"),

            ("P", "写运行时校验用 raise 不用 assert（`python -O` 会把 assert 整段移除）",
             "外部实证（2026-11-19 六类来源查证，起因：给 `tier_matcher.py` 加 `assert_route_shape` 时差点用 assert）："
             "cruijff_kit issue #86 原句「`assert` **Can be disabled with `-O` (optimize) flag, removing all asserts at runtime**」，"
             "只该用于内部不变量 / 调试期自检 / 文档化假设，**不用于验证外部输入、不用于生产错误处理**；"
             "火山引擎文章同结论「**assert 本身是面向开发调试的语法，Python 以优化模式（`python -O`）运行时所有 assert 语句会被直接移除**，"
             "不适合用于生产环境的业务校验」。正确做法：显式 `raise ValueError(...)` 并带上违规的具体值。"
             "校验放哪：优先放在边界（测试里必跑、`lab selfcheck` 里跑），不是每次调用都跑——"
             "实测 342 条全量校验 0.03 ms、`path_options()` 含校验 0.2 ms，当前不是瓶颈所以没挪，但换到高频路径前要先量。",
             "用 assert 写校验更短更像 Pythonic，而且正常跑测试也真会红——所以很容易一直用下去。"
             "风险在于只在 `-O` 下暴露，而我的脚本从来不加 `-O`，等于**永远发现不了**；"
             "更隐蔽的是它不会报错、不会警告，校验就那么消失了。",
             "①`grep -n \"^\\s*assert \" <文件>` 找有没有用 assert 做校验的；"
             "②`python -O -c \"import <模块>; 触发一次坏数据\"` 应仍然抛错而不是静默通过"),

        ],
    },
    {
        "domain": "测试 / 回归 / 交付验收",
        "words": ("测试", "验收", "回归", "交付", "做完了", "验证", "没改坏", "差分", "等价性", "证明正确", "自证", "核实", "数字", "出处", "lab test", "pytest", "用例", "跑测试",
                     "两轴评审", "规范 vs 需求", "代码味道", "做错了事", "破坏约定", "代码评审", "评审", "review", "检查代码", "代码质量"),
            "tools": "lab test / lab selfcheck / lab claims（说做完了先对证据）",
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
            ("H", "验证工具先自证：拿一个已知答案的样例跑一遍",
             "抽取/校验脚本自己会错——正则放宽、切片越界、编码坏掉，都会安静地吐出一堆假结果，而且看起来像「真发现了问题」",
             "多花 30 秒造样例；样例要含已知的正确项与已知的错误项",
             "2026-11-13 记忆路径验证：第一版让正则把路径一路吃到空白，抽出 263 处、报 228 处不存在；点开全是路径尾巴粘了括号/反引号/中文说明。放窄后只剩 28 处真不存在，其中一半还是写明了的「已删」历史记录"),
            ("I", "引用数字的处置：能核到出处的保留，核不到的改定性",
             "不删、不编、也不硬凑百分比——能指到官方原文的留下并注明机构年份，指不到的改成趋势/程度表述",
             "要真的打开原文；二手转述的数字最容易在这一步露馅",
             "2026-11-13 论文正文：微软 WTI 2021 新闻稿核到「73% 员工希望保留弹性远程」（31 国 3.1 万人），67% 核不到 → 改「同一调查亦显示员工对面对面协作仍有明确需求」；McKinsey 20%–25% 未取到原文 → 改行业集中度的定性判断"),
            ("J", "两轴分离评审：Standards（符不符合仓库文档化的规范）× Spec（有没有忠实实现原始需求），各跑一个并行 sub-agent，报告不合并不重排",
             "两种失败性质不同——「符合所有规范但做错事」和「按需求做但破坏约定」，混在一起会互相掩盖；分开才能各说各的，也不至于用一轴的成绩抵消另一轴的窟窿",
             "要两份额外上下文；没有 spec 时 Spec 轴只能跳过并写明；基线代码味道（Mysterious Name / Data Clumps / Feature Envy 等）永远只是 judgement call，不是硬违规",
             "两份报告各自有结论；能指出「这条是规范问题还是需求问题」；不要挑「哪个更严重」的跨轴排名——排名本身就会让一轴盖住另一轴"),
        ],
    },
    {
        "domain": "写文档 / 报告 / 笔记",
        "words": ("文档", "报告", "笔记", "写一篇", "总结", "整理", "说明",
                  "决策日志", "记日志", "记录", "复盘",
                 "架构图", "流程图", "时序图", "画个图", "图表", "周报",
                 # 2026-11-08 加：时间表述也属于「写出来的那句话准不准」
                 "时间", "早上", "下午", "晚上", "昨天", "前天", "上周", "上个月", "多久"),
            "tools": "write（成文） / lab lint（排版） / lab journal（留痕）",
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
                  "课件", "版式", "母版", "讲稿", "备注页", "deck", "pptx", "AI 味", "塑料风", "模板感", "五个指纹", "eyebrow", "卡片套件", "奶油底"),
            "tools": "ppt-craft skill / office_pptx / lab ocr（读模板图量版面）",
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
            ("K", "PPT 也过一遍「AI 生成五个指纹」（详见域 2 F）",
              "PPT 最常见的三种：暖奶油底+衬线+陶土色、SaaS 卡片套件、标题上全大写 eyebrow。**中文 PPT 还有第四种：每页左上角色块小标题 + 右下角页码 + 通栏渐变色条**",
              "它不是审美判据，是「是不是套路」的判据；中文排版三条硬规则（E 条）优先级更高",
              "做之前先定一句「这一页要让观众记住什么」，配色 / 字体 / 版式都要能对回这句话；**对不回就是套路**"),
        ],
    },
    {
        "domain": "找资料 / 调研",
        "words": ("查资料", "调研", "搜索", "网上", "文献", "论文", "什么是",
                  "打不开", "403", "405", "反爬", "抓不到", "读不了", "教学材料", "星数",
                  "视频", "抖音", "短链", "别人推荐", "这个项目", "开源项目", "仓库", "源码",
                  "看源码", "比我的好", "值不值得装", "成熟度"),
            "tools": "web_search（找） / web_fetch（读全文） / lab cdp（被反爬时开真浏览器）",
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
            ("I", '外部推荐（视频 / 帖子 / 别人说「这个好」）→ 先查仓库、再看源码，最后逐项对比我的能力',
                '治「凭我有 web_fetch / lab cdp 就说没新东西」这个病。2026-11-17 我这样判 Scrapling 被用户当场否——'
                '真去 GitHub 读完，它在反爬（TLS 指纹伪造 / Cloudflare Turnstile 绕过）、代理轮换、'
                '爬虫框架（断点续爬 / AutoThrottle / 缓存重放 / robots.txt）上全面强过我。'
                '**项目真名常常不在标题里**：视频只说「github 这个 skill」，真名在评论区 / 「大家都在搜」里（得搜 scrapling）',
                '一次要 3–5 分钟（search + tree + 2–3 个 contents）；raw.githubusercontent 拿大 README 会 30s 超时，'
                '改用 API 的 base64 content；star 数只说明热度，不说明合不合我',
                '`api.github.com/search/repositories?q=<名字>&sort=stars` 确认仓库（star/fork/语言/许可/最后 push/open issues）'
                '→ `git/trees/<branch>?recursive=1` 看结构 → `contents/<关键文件>` 拿源码'
                '→ 清单每一项都写清「比我强 / 差不多 / 比我差」，只写「吸收 / 不吸收」不算'),
        ],
    },
    {
        "domain": "记忆管理",
        "words": ("记忆", "记住", "忘掉", "以前说过", "存一条", "验证", "过期", "假记忆", "memcheck", "记忆副本", "记忆重复", "同一份知识存两份", "索引行", "索引不是正文", "措辞重合"),
            "tools": "memory_save/update（写） / lab recall（读） / lab assets（盘点）",
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
            ("F", 'memory_search 精确关键词搜（多词 = 全部匹配）',
                '比 lab recall 更可控——recall 是「按任务原话提词」，search 是「我知道要找什么词」；命中结果按相关度排序',
                '不做同义扩展，词不对就搜不到；要用 `includeDeprecated` 才看得到被取代的',
                '搜一个已知存在的词，第一条就是那条记忆'),
            ("G", "批量清理记忆库（231→224 实测，2026-11-13）",
             "五步：①先备份 `memories.json` 到工作区的备份目录（用户 2026-10-27 定的规矩：大改前后各一份）；②写一次性盘点脚本（统计重要性/日期/标签 Top + 三类可疑：正文含旧数字的正则表、标题前 12 字重复、≤3/5 且正文 <60 字），**别把 200+ 条正文倒进上下文**；③逐类判定：被新版本取代的删、同一主题多条合并成最新那条、纯一次性事件删、历史事实（当时真发生过的事故记录）保留不改；④执行用 `memory_update`（改正文/标签/重要性）+ `memory_forget`（删），**不要手改 memories.json**（有跨进程锁）；⑤`memory_list` 复核条数、`lab pre` 复跑",
             "两个容易判错的地方：①**「被取代」不等于「可以删」**——某些记忆前半段过时、后半段仍然有效（例：dsh-ops 0.5.2 的 discover 规则在 0.5.4 仍然成立，只需改数字不能删）；②**历史记录不要改**（「2026-11-04 时 lab 有 27 个子命令」是当时的事实，改成 48 就是篡改）。另外记忆里带数字/版本号/路径的断言，改的时候要顺手写下复核方式",
             "条数下降且分布合理（5/5 基本不动、删的主要是 3/5 和 4/5）+ `memory_list` 能查到改过的条目 + 每条删除都能说出「被谁取代」或「为什么没价值」"),
            ("H", "记忆验证四类：路径 / 版本 / 数量 / 大小",
             "按断言类型分开验：路径查存在性、版本比对已装模块、数量现数、大小现看；历史记录（已删/已卸载）不改，只改「当前状态」断言",
             "要写扫描脚本；验证脚本本身先自证（见测试域 E）；233 条扫一遍约两分钟",
             "2026-11-13 实测：路径 0 条假、版本查出 3 条过期（dsh-ops 0.5.2→0.5.4、dsh-memory 0.6.16→0.6.17）、数量 1 条过期（路线库 236→240）；判据——「现版本 X」「N 条」「N B」这类当前值必然腐烂，改写成查询命令（node -e … / lab --help）"),
            ("I", "`lab recall \"<任务原话>\"`（按任务提词，别自己猜关键词）",
             "一条命令把「按原话提词 + 命中哪条记忆 + 该走哪条路线」合成一次；`--audit` 看历史命中率，"
             "`--use <id> --note ...` 回写这条记忆有没有帮上忙",
             "它按字面词匹配，任务描述太泛（「帮我弄一下」）会提不出东西；提词结果只是候选，不是结论",
             "输出带「提词 / 命中记忆 id / 建议路线」；`--audit` 命中率长期低于 3 成说明词表该改"),

        ("J", "`lab memcheck`（措辞重合清单，不是副本判定）",
         "把「同一份知识存两份」变成可扫：扫 memories.json × SKILL.md，按最长公共子串占比打分，`--min-ratio 0.3` 只看重复句多的",
         "**分数 1.00 只说明有一句完全重合，不等于整条是副本**——2026-11-17 抽查 12 条全误报；命令名 / 判据原文 / 用户原话本来就会两处都出现；**判是不是副本必须读 memories.json 正文，不能看系统提示里那行索引**（那是摘要不是正文）",
         "`lab memcheck --min-ratio 0.3` 列几条 → 逐条读正文判「哪边更完整」：记忆只有标题+原话 → 改指针；记忆有 SKILL.md 没有的细节 → 该补的是 SKILL.md"),        ],
    },
    {
        "domain": "会话检索 / 找以前的对话",
        "words": ("以前", "上次", "会话", "聊天记录", "之前说过", "找一下", "解压会话", "会话文件", "zstd", "原始事件"),
            "tools": "lab sessions（按关键词） / lab since（按时间）",
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
            ("E", "直接读原始会话文件：多帧 zstd 要用 stream_reader（2026-11-14 实测）",
             "`session.v4.jsonl.zstd` 是多个 zstd frame 拼起来的：`d.decompress(全部字节)` 报 "
             "`could not determine content size in frame header`；`decompressobj().decompress()` 只解第一帧（1 个事件）。"
             "正确写法 `with d.stream_reader(fh, read_across_frames=True) as r: 循环 read(1<<20)`，"
             "实测一个 1.8 MB 文件解出 2,665 个事件",
             "解压后是完整 JSONL，别整段打印；要按事件类型统计或只取尾部 N 条",
             "事件条数、首事件 `type=session`、尾事件 `turn/end` 能对上，才算读全"),
        ],
    },
    {
        "domain": "开发协作 / 拆活",
        "words": ("并行", "队友", "拆", "同时做", "子智能体", "多个人",
                  "设计树", "frontier", "逼问", "问完一轮", "推荐答案", "事实自己查", "别问用户", "取舍", "你先查一下", "有没有时间", "故事线", "让人选", "三个方案", "选哪个", "形容词", "SPEC", "量化需求", "说法含糊", "大气一点"),
            "tools": "Agent Teams（spawn_teammate） / workflow（大规模 fan-out） / team_task_*",
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
            ("H", "设计树逼问：把方案拆成决策树，每轮问完整个 frontier（前置条件已满足的决策），每题编号 + 给出我的推荐答案，让「是」= 接受推荐",
             "一轮把能问的问完，不挤牙膏；给推荐比开放式提问更容易得到有效回答；答案会重塑树，下一轮 frontier 才准",
             "找事实是我的活不是用户的——能自己查的（代码/文档/--help/配置）别问；不阻塞（正在跑的探索是未定前置，只等它下游的问题）",
             "frontier 空了 = 每个分支都走过、没有默默假设的东西；用户确认达成共识前不动手。**说出「你能不能…」「你有没有…」「要不要…」之前先自问：这是取舍（用户定）还是事实（我查）？** 2026-11-17 两次反例：「你现在有没有时间测试 ControlNet」（我自己能跑一张）、「要不要把 memcheck 注册成子命令」（我自己能判）"),
        ("J", "给 3 条故事线让人选，而不是问「你想要什么」：`references/story.md` 每行一句「A 把 X 变成 Y / B … / C …」", "问「你想要什么」等于让用户自己发明方案；给三条具体的他只需指一个，而且三条摆一起能逼出他真正在意的是哪一维", "多花一轮；用户已经明确说了方向时不用问，直接做", "三条各有一句「关于什么 / 怎么走」；用户能一句话挑中"),
        ("I", "每个形容词变数字：写 SPEC 时把「快一点 / 清楚一点 / 大气一点」换成可量的值", "形容词是别人脑补的入口——「大气」在两个人脑子里是两个东西，改完谁都不认账；换成「字重 700 / 主色 #1a1a1a / 一屏 3 块」之后对错立刻能判", "有些维度确实难量化（气质、调性），那就给 2-3 张参考图，别硬编数字", "指着 SPEC 能问出「这句『大气』具体是多少」；答不上就是没换成数字"),
        ],
    },
    {
        "domain": "自动化 / 定时 / 无人值守",
        "words": ("定时", "每天", "自动", "计划任务", "无人值守", "后台跑",
                  # 2026-11-07 补：用户原话「解决 DSH-Metric-W2 从未跑过」**一个词都不命中**，
                  # 因为没人会用「计划任务/定时」这种分类词说自己要干嘛——他们说任务名、说症状。
                  "DSH-", "schtasks", "从未跑过", "跑不起来", "不执行", "没在跑",
                  "触发器", "StartBoundary",
                  # 2026-11-15 补：新路线 I（上次失败先手动跑一次）需要被「失败/重跑」这类说法命中。
                  "上次失败", "LastTaskResult", "手动跑", "重跑", "计划任务失败"),
            "tools": "schtasks（建任务） / lab tasks（查结果码） / lab unattended",
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
            ("I", "计划任务「上次失败」先手动跑一次，再判断是不是真坏（2026-11-15 实测）",
             "`DSH-Ledger-Collect` 告警时先手动跑同一脚本：`collect.py` 成功、余额没降且没重复记账 → 判网络抖动/上游超时，"
             "任务不用改，下一个整点自己重跑；`env_doctor` 的 WARN 会自己消失",
             "手动跑会写一次账（靠幂等键才安全）；脚本本身不幂等时，手动重跑可能重复记账/重复发消息",
             "手动跑 rc=0 + 关键数字合理（余额、条数）+ 下次计划时间到了看 `LastTaskResult` 是否 0"),
        ],
    },
    {
        "domain": "备份 / 恢复 / 回滚",
        "words": ("备份", "恢复", "回滚", "改坏了", "退回",
                  "还原", "旧版本", "更新前", "更新后坏了", "退回去", "留个底", "存档",
                  "快照", "回滚点", "版本回退", "降级", "恢复原样", "老版本", "退回旧版"),
            "tools": "lab snapshot（文件级，可 undo） / trash.ps1（进回收站） / robocopy（整目录）",
        "routes": [
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
        "words": ("自检", "体检", "健康", "有没有问题", "检查一下自己", "时间", "日期", "昨天", "前天", "上周", "上个月", "多久", "几天", "说错", "算错天", "掌握力", "适配性", "冒烟", "试跑", "跑一遍看看", "漂移", "对账", "卸载", "卸掉", "删插件", "拆插件", "selfcheck", "机制一致",
                  "证据", "验证过", "没验证", "瞎说", "说瞎话", "凭什么", "有依据吗", "真的吗", "你确定", "别乱说", "确认一下",
                  # 2026-11-14 补：读清华 PDF 吸收「幻觉五类」后加，否则用户问「你有没有幻觉」命中不到自我体检。
                  "幻觉", "编造", "编的", "无中生有", "数据误用", "语境误解",
                  # 2026-11-14 补：吸收《DeepSeek 与 AI 幻觉》的高发场景表，
                  # 否则「医疗诊断/金融预测」这类问法命中不到自我体检。
                  "医疗诊断", "金融预测", "未来预测", "数学证明", "法律咨询", "安慰性回应",
                  # 2026-11-15 补：新路线 O（sidecar 加载了新代码没）的触发词。
                  "加载了新代码", "进程启动时间", "CreationDate", "重启后生效", "加载了没", "mtime", "配置生效", "配置有没有生效", "discover", "PUBLICATION", "工具报错",
                  # 2026-11-17 补：`lab onboard` 的触发词（体检报告说它 23 次调用、路线库 0 提）。
                  "能力清单", "onboard", "有什么工具", "有哪些工具", "装了哪些插件", "我会什么",
                  # 2026-11-18 补：`lab sync` 的触发词。用户 m15986 定「同步一下自身状态」= 跑它，
                  # 不补这些词，这句话命中不到本域，sync 就永远想不起来用。
                  "同步自身状态", "同步一下自身状态", "同步一下", "同步状态", "同步六面", "六面",
                  # 2026-11-18 补：`lab capsnap`（能力快照）的触发词。用户问「现在有几个能力/多少版本」
                  # 之前，应该先跑快照而不是凭记忆报数。
                  "能力快照", "快照", "capsnap", "现在有几个", "多少个子命令", "版本对不对", "数字对不对",
                    "新工具", "要不要接", "值不值得装", "视频推荐", "开源项目",
                    "要不要用", "该不该装", "比我的强吗", "多了一个工具"),
            "tools": "lab selfcheck（机制漂移） / lab health（路线库） / lab sync（同步状态） / env_doctor（环境）",
        "routes": [
            ("A", "env_doctor（运行态总检）",
             "一条命令查沙箱/bili/目录/任务/插件/工具",
             "默认不查 ssot（要跑 1 分钟）",
             "需要处理的项都是 0"),
            ("B", "lab selfcheck（机制 vs 磁盘）",
             "文档里的计数/路径/子命令一致性",
             "只管文档",
             "0 处漂移"),
            ("D", "lab tools + lab skill（使用率/熟练度）",
             "哪些工具零调用、哪些用得费劲",
             "零调用分五种原因，不能直接删",
             "连续两周零调用的有处理记录"),
            ("F", "lab since + 系统提示的时间行（说时长前必跑）",
             "把「多久以前」从手算变成命令：lab since 2026-10-20 → 19 天前；"
             "系统提示每轮带 Time sampled，那也是锚点",
             "只能算「从某天到今天」，算不了「两件事隔多久」（要跑两次或自己减）",
             "同一天跑 lab since 2026-10-20 天数跟手算一致"
             "（2026-11-08 实测 19 天，而我凭印象说的 18 天是错的）"),
            ("G", "装/卸插件之后跑一次 `lab selfcheck` 做能力对账（2026-11-13 实测：装 agentero 当场报 2 处漂移；**卸载比安装更麻烦**——包、cordis.patch 条目、能力清单、记忆、路线库案例引用、env_doctor 快照、客户端 bundle 七处都要跟着改）",
             "装插件改的是「能力」本身：能力清单没记它、能力指纹变了，两处都会拦提交；补齐文档 + `lab selfcheck --update-fingerprint` 重记基准",
             "指纹会把当期状态记为基准；漏改文档就等于把错的记成基线",
             "`lab selfcheck` 打「机制与能力一致」；`lab commit` 不再被拦"),
            ("H", "删插件的七步：卸 bundle → 清磁盘残留 → 改能力清单 → 改记忆 → 改规则文档 → 改路线库案例 → 重算指纹",
             "2026-11-13 卸载 agentero 实证：包卸了之后还有五处磁盘残留（vault 1.5 MB、CLI 32 MB、PATH 里的 exe 32.9 MB、临时目录、源码）和五处文档残留（能力清单、记忆、SKILL.md、路线库、指纹），少清一处下次就会对着不存在的工具做计划",
             "要手动核对的地方多，一次 20-30 分钟；`lab selfcheck` 只抓已登记的口径，抓不到 PATH 和数据目录",
             "七步走完跑 `lab selfcheck --update-fingerprint`，再 `grep -ril <插件名>` 确认剩下的只有历史记录"),
            ("I", "`lab selfcheck`（16 组机制 vs 磁盘，改完机制立刻跑）",
             "把「文档里说的」和「磁盘上真有的」逐条对：文档互引、@local 装机、README 覆盖、路线库覆盖、规则触发、"
             "插件脚本覆盖、知识源路径、能力指纹、自检时效——2026-11-14 实测 16 组全绿、7 秒出结果",
             "它只查已登记的口径；抓不到 PATH、数据目录、运行时行为（这些靠 env_doctor / only=health）",
             "结尾打「机制与能力一致：文档里说的，磁盘上都有」且退出码 0；报漂移先修再提交"),
            ("J", "`lab test`（196 个用例，约 8 秒）",
             "改完 lab 源码先跑它：pytest 覆盖 encoding / fact / snapshot 等；2026-11-14 实测 `196 passed in 7.92s`",
             "只测已写用例的部分；新功能的回归要自己补用例，否则全绿也不证明对",
             "`196 passed`（或更多）且 0 failed；失败先看是不是自己刚改的那个模块"),
            ("K", "`lab tools`（谁真的在用，谁从没被调过）",
             "按会话统计工具调用次数，一眼看出「写了但没人用」的工具；连续两周零调用的该删或补触发信号",
             "统计的是会话里的工具名，跨会话才有意义；不能当「我会不会」的证据",
             "输出带「N 个会话 / M 种工具」+ 排行；排行为 0 的进淘汰审视"),
            ("L", "`lab claims` / `lab fact`（说话前对证据：完成声明、数字断言）",
             "2026-11-14 用户 m01661 定的第 25 条（实践是检验我所说话的唯一标准）的工具面："
             "说「做完了/修好了」之前跑 `lab claims --chat --days 1`，看有没有光说不带数；"
             "说具体数字/版本/路径之前跑 `lab fact \"<那段话>\"`，把它提取出来并给复核命令",
             "claims 只认它认识的完成句式（做完了/修好了/建成了），推测句和引用句不算；"
             "fact 只提取不判断真假，真假还得自己跑命令验",
             "claims 输出里没有「光说不带数」的条目；fact 给的复核命令我能执行过再开口；"
             "没验证时只说三种话：我还没验证 / 我推测（依据 X）/ 引用：Y 说的"),
            ("M", "交付前过一遍幻觉五类：数据误用 / 语境误解 / 信息缺失 / 推理错误 / 无中生有",
             "清华《DeepSeek 从入门到精通》P31 的五类分类（教学材料，非官方；我 2026-11-14 读后吸收）——"
             "每一类都对应我真实犯过的一个错："
             "①数据误用：引用了数据但细节不符（11 分钟前说成「昨天」）"
             "②语境误解：答的不是他问的（他问「这个对话框还能用吗」，我答「为什么不能用」）"
             "③信息缺失：没拿到信息就编（把 bili 的 |sub: 当子智能体，用户一句「我没用过子智能体」推翻）"
             "④推理错误：逻辑环节跳了（只看 projcache 表面 43 万就判「不是上下文爆」，实际请求 166 万）"
             "⑤无中生有：完全虚构（编一句用户没说过的话写进压缩摘要）",
             "五类是自查清单不是分类学；对不上号说明还没真查，不是「我很干净」",
             "交付前逐类问一句「刚才那段有没有这个形状」，命中任一就回去补证据；"
             "和第 25 条配对用：第 25 条管「说没说成事实」，五类管「说错了是哪一种」"),
            ("N", "按幻觉高发场景定验证强度（比例尺 + 场景表 + 四种锚定句式）",
             "清华《DeepSeek 与 AI 幻觉》38 页（2025-02 教学材料，2026-11-14 读完吸收）给的三组可用事实："
             "①比例尺——通用提示 100 条：DeepSeekV3 2% / R1 3% / 豆包 0%；事实性 300 题（健康/科学/历史/文化/音乐）：V3 29.67% / R1 22.33% / 豆包 19%，"
             "**事实性问题高一个数量级**；且推理模型不更准（Vectara 摘要任务 R1 14.3% vs V3 3.9%，原因是逻辑过度外推）。"
             "②场景表——极高风险（断言前必须外部核对）：医疗诊断、金融预测、未来事件预测、数学证明延伸、安慰性回应；高风险（至少标不确定性）：开放域续写、多跳推理、多轮对话、法律咨询。"
             "③四种约束句式（查资料时用）：时间锚定「基于 2023 年前公开文献」、知识锚定「基于《X》，不明确注明暂无可靠数据」、领域限定「作为 X 专家…」、置信度声明「不确定用[推测]标签」。"
             "反向提醒：联网搜索只把事实性幻觉 29.67%→24.67%（约 5 个点），联网不等于对。",
             "这是别人 2025 年的实测数字（DeepSeekV3/R1），当前模型版本没测过——只能当量级参考，不能当「今年还是这样」；场景表是设计出来的风险分级，不是错误率排名；"
             "四种句式是给「人写提示语」用的，我不是靠提示语干活，真正能搬过来的是「在什么场景要多留一道核对」",
             "断言落在「极高」场景 → 输出前必须有一次外部核对并写来源；查不到来源就写「这是我推测的（依据 X）」；"
             "落在「高」场景 → 至少标一句不确定性；其余场景可以直说"),
            ("O", "sidecar / 插件是否加载了新代码：比进程启动时间和文件 mtime（2026-11-15 实测）",
             "改完 bili 的 `dist/index.js` 后，`Get-Process node | ? {$_.Path -like '*billion-context*'} | select Id,CreationDate` 拿进程启动时间（14:47:18），"
             "与文件 `LastWriteTime`（14:43 左右）比：启动晚于修改 = 已加载；早于修改 = 还是旧代码、必须重启。比等新行为出现更直接",
             "只能证明「进程加载了这份文件」，不能证明「补丁在真实场景生效」——后者要看业务日志（`nudge usage` 与 `inbound` 是否对得上）",
             "进程 CreationDate > 文件 LastWriteTime；配合 `patch-bili.mjs --check` exit 0 与 bili.log 里的行为数据"),
            ("P", "开工前先看「我有什么」：`lab onboard`（一次列全插件 + lab 子命令 + 调用统计）",
             "`lab onboard` 默认列全部插件（名字/版本/启用状态/被调用次数）+"
             "全部 lab 子命令；`--only <子串>` 只看某个，`--no-calls` 跳过日志统计会快几秒。"
             "治的是「凭记忆数能力」——记忆里写着 21 个插件、实际可能 24 个，问一句就知道累",
             "要读会话日志统计调用次数，默认慢几秒；结果是随时间变的快照，不是稳定文档",
             "`lab onboard --no-calls` 里的插件条数应等于 `plugin_manager list_plugins` 的条数；"
             "「用过」列能标出从没被调用过的工具"),
            ("Q", "`lab sync --type <4类> --subject \"<主语[|别名]>\"`（同步自身状态；必写只有记忆）",
             "按主语搜六面，把每处首行和数字摆出来——判据不是「缺不缺」，是「不写会不会永久丢」："
             "只有记忆库会（下一个我唯一能读到的地方），路线库/机制文档/索引台账/决策日志/回写缺一次下一轮还能补，"
             "所以只提示、不改退出码。回写面用 `tier_matcher.path_options()` 映射相关域 + 查 `event=pick` 的 `used` 域，"
             "不要求 note 含主语（原写法要求 note 含关键词，等于「能被搜到」代替「真回写了」）",
             "它只显示各处怎么说的、不判断该不该改；回写要真走过路线库才自然命中——没走就用 "
             "`--acknowledge writeback --subject \"<主语>\" --reason \"<一句>\"` 留出口，别为过检查造数据；"
             "**主语必填**（2026-11-18 定）：无主语的跳过会命中任何后续检查，等于永久豁免",
             "`--check` 报「必写面齐」；建议面缺能说清为什么可以缺；改完 `lab test` + 基线重建再提交"),
            ("R", "`lab capsnap`（能力快照：数字从真值采，不写死）",
             "把四类容易过期的数字从真值采到 `E:\\DS公作区\\架构文档\\能力快照.json`："
             "`lab --help` 的子命令数（运行时 build_parser，不是数源码 add_parser）、"
             "profile 每个包的真版本（link 的读源码目录 package.json）、"
             "`tier_domains.PATH_OPTIONS` 的域数/条数、`memories.json` 的活跃条数与 5/5 条数。"
             "文档里写「见快照的 X 字段」而不是硬编码——治的是「同一个数字散在多处、改一处忘三处」",
             "只治「读到旧值」，**治不了「压根没读到」**（2026-11-18 我把清单里那半句「版本 0.1.3 → 0.2.0」"
             "读漏了，快照救不了这个）；和 `lab selfcheck` 的漂移检测有重叠，别指望它替代 selfcheck",
             "`lab capsnap` 的四个数字与 `lab --help` / 实测一致；快照 mtime 晚于最近一次能力变更"),
            ("S", "外来能力三句话：我现在用什么 / 它比我强在哪（具体事）/ 代价是什么",
             "用具体命令说出「我现在怎么做的」，再指出「我做不到的某件具体事」，最后算钱·维护·学习·风险——"
             "**第②句答不出就说明它没提供我缺的东西**，不缺就不用装；缺了也先看代价划不划算",
             "容易停在「它有这个功能」：功能名不是对比，要比的是同一件事上谁做得到、谁做不到",
             "`lab tier \"有人推荐了一个新工具，要不要接\"` 应命中本域并打印 S 条"),
        ],
    },
    {
        "domain": "成本 / 预算 / 上下文",
        "words": ("花多少", "成本", "预算", "token", "上下文", "太长了", "压缩", "命中率", "缓存命中", "缓存", "折叠", "bili", "acp_cache",
                  "深度求索", "一直转圈", "卡在", "超限", "maximum context length", "derived-persona", "人格派生", "请求超了",
                  # 2026-11-15 补：新路线 M（值存在但不参与判断）需要能被「没生效/低估」这类说法命中。
                  "没生效", "机制没生效", "没参与判断", "算了没用", "低估", "估算不准", "usage 基数"),
            "tools": "lab cost（官方真数） / lab balance（余额估算） / lab tier（会带预算提示）",
        "routes": [
            ("A", "lab cost --session / --official",
             "本地账 + 官方账对照；实测官方/本地 1.38 倍",
             "官方那路要 CDP 起浏览器",
             "两个数能对上量级"),
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
            ("K", "会话卡在「深度求索中」原地转圈：三步取证（2026-11-14 实测）",
             "① `bili.log` 搜会话 id：有 `forward POST` 但无 `← upstream 400` 就是还在等上游；有 "
             "`maximum context length is 1048576 ... you requested N tokens` 就是请求体超限，N 是真实账。"
             "② 会话文件 `sessions\\...\\session.v4.jsonl.zstd` 的 mtime/size 没变 = 消息**根本没到服务端**，"
             "卡在前端或压缩环节。③ `storages\\session_projcache\\...json` 里 `turnBoundary.openTurnStartSeq` 非空 = 有未完成 turn。"
             "关键判据：日志出现 `preflight aborted (the client disconnected during compression)` = bili 正在压缩时客户端断开，"
             "**压缩没跑完，超限请求照样发出去**——切会话、刷新、超时都会造成这个。"
             "④ **usage 基数可能是缓存增量不是全量**：同一会话 `[acp-usage] input=` 与 `request: N msgs, inbound=X MiB` 差 3 倍以上，"
             "说明分母被上游 usage 污染（百炼缓存命中只报增量），此时「才用 11% 很安全」是假的",
             "别只看会话表面 token（projcache `contextPressure.surfaceTokens` 可能只有 43 万），"
             "真实请求体能到 166 万；`sub:` 前缀不是子智能体（见 L）",
             "能从 bili.log 指出「哪一次请求、多少 tokens、对哪个窗口超了」，且能说清是「没到服务端」还是「到了被 400」"),
            ("L", "`sub:` 前缀是 bili 的派生人格，不是子智能体（2026-11-14 教训）",
             "日志形如 `derived-persona: session-X -> session-X|sub:<hash> (persona text changed without continuing history — persona lane)`："
             "系统提示（人格文本）变了但历史连续时，bili 给会话派生一条新车道，**带着全部历史**重发。"
             "同一天改配置/改记忆多次 → 反复派生 → 会话上下文反复膨胀",
             "看到 `|sub:` 先别当子智能体：去会话文件 grep `subagent` / 那个 hash，"
             "会话 JSONL 里 0 命中就证明它不是 agent（我 2026-11-14 就是没查证，被用户一句「没用过子智能体」推翻）",
             "能贴出 `derived-persona` 的原始日志行 + 会话文件里对 subagent 的搜索结果（0 条）"),
            ("M", "一个值「存在但不参与判断」——机制生效四层，缺一层就等于没有（2026-11-15 实测）",
             "bili 的 `localInputEstimate` 被算出来、挂到 `stats.localInputEstimate`，但 `statusInputBaseline()` 只在 "
             "`usageAnchorCycleStale()` 为真时才读它；正常 settle 把 `contextTokensSource` 设成 \"usage\" → 永远走 usage 分支 → "
             "本地估算**算了但永不上场**。修法：两者取 max（`patch-bili.mjs`），让「本地估算说快爆了」也能触发压缩",
             "这层比「改了数据没生效」更深：数据确实在内存里、也变了，只是判定函数没读它；光 grep 赋值点会以为它生效了",
             "追「读」不追「写」：grep 该字段所有出现位置，逐个看是不是在 if/判定里被用；只赋值不判定 = 不存在。"
             "机制生效四层——数据写了 / 被主体调用 / 进程已加载 / 有可见差异，四层分开验"),
        ],
    },
    {
        "domain": "桌面 / 浏览器操作",
        "words": ("点一下", "打开网页", "点击", "浏览器", "桌面", "鼠标", "cdp", "devtools", "调试端口", "网页截图", "截个网页", "网页自动化",
                  "点不到", "点不了", "点了没反应", "坐标", "headless", "物理点击", "帮我点", "抖音", "视频链接", "分享链接", "看视频", "b站", "视频号", "视频专用"),
            "tools": "lab cdp（操作已开网页） / video-watch.ps1（看视频，用完关） / lab desktop（物理点击） / agent-desktop MCP（读无障碍树）",
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
            ("E", "`lab cdp`（Chrome DevTools Protocol，操作网页不抢焦点）",
             "连本机 Edge/Chrome 的调试端口，可开页/取 DOM/截图/执行 JS；比坐标点击稳，且不挪鼠标；"
             "2026-11-14 实测 `lab cdp --help` 与窗口枚举正常",
             "要先带 `--remote-debugging-port` 启动浏览器；页面没开调试端口就连不上；"
             "headless 必须成对关闭（2026-11-08 留过幽灵进程）",
             "能贴出目标页 URL + 取到的元素/截图路径；连不上先查端口与浏览器启动参数"),
            ("F", "坐标点不到/点了没反应：先分清楚是哪一层的限制（2026-11-14 实测）",
             "三条路各有边界：① `mcp__desk__desktop_mouse_click` 在 headless 模式**直接禁用**"
             "（`mouse-click moves the cursor and is disabled in headless mode`）；② 语义 click 对 treeitem 可能"
             "`Target is not actionable: supported_action`（直接语义投递不可用、物理回退被策略拒）；"
             "③ 绕开前两者用 `lab desktop click x y --yes`（Win32 输入，不受 MCP headless 限制）。"
             "坐标别从截图直接搬：截图是物理像素（1923×1234），`lab desktop` 是逻辑像素（1707×960），"
             "要先 `desktop_list_windows` 拿窗口 bounds，点一次后立刻用 `Get-Process | ? MainWindowTitle` 读窗口标题验证落点",
             "列表项间距约 35 逻辑像素，偏一点会切到相邻会话（只是切视图、无损，但会打断用户）；"
             "别连点超过 3 次；点错立刻点回来",
             "点完 1 秒内读到的窗口标题 = 想要的会话名，才算点对"),
            ("G", "用户发来抖音/视频分享链接：先别答\"看不了\"",
             "四步：①短链用 `curl -sL -o NUL -w \"%{url_effective}\"` 拿真实地址（`web_fetch` 会报 cross-origin redirect 不跟随）；②页面是纯 JS 壳时 `web_fetch` 只有空 HTML（`RENDER_DATA`/`_ROUTER_DATA` 全 0），改走 `lab cdp goto <url> --wait 25`（Chrome 带 `--remote-debugging-port=9222` 和独立 `--user-data-dir`）；③抖音登录弹窗会盖住画面，但 `<video>` 在后台播（`currentSrc` 是 blob:、`paused:false`）——eval 把 video 提到最上层 `v.style.cssText=\"position:fixed;left:0;top:0;width:1024px;height:576px;z-index:2147483647;background:#000\"` 再截图就绕过去了；④要看中段就 eval 设 `v.currentTime=T` + sleep 1.8s 再截图",
             "每次导航后 raise 都要重做（样式不跨页面存活）；`lab cdp eval` 的 JS 必须用 `--file` 传（内联换行会被 PowerShell 拆坏，报 unrecognized arguments）；弹窗点不掉（选择器不匹配，eval 返回 clicked 0）；只能看不能下（blob 源）",
             "截图里有画面 + `document.title` 是视频标题 + `v.duration` 是真实秒数（不是 NaN）"),
            ("H", "看视频用「专用 Chrome」，用完就关（用户 2026-11-15 定）",
             "`E:\\DS公作区\\tools\\video-watch.ps1 -Url <链接>` 起有头 Chrome（`--remote-debugging-port=9222 --user-data-dir=E:\\DS公作区\\.cache\\chrome-video --window-size=1280,860`）并打开；`-Close` 关掉该 profile 的全部进程。用户原话：只有他分享视频时拿出来用，其他时候关掉别占内存",
             "profile 留在磁盘（约 20 MB 含缓存，不占内存）；忘了 `-Close` 就一直开着；有头窗口会出现在桌上打扰用户",
             "启动前 `Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | ? {$_.CommandLine -like '*chrome-video*'}` 应为 0 条；`-Close` 后应回到 0 条"),
        ],
    },
    {
        "domain": "音频 / 视频",
        "words": ("视频", "音频", "剪辑", "ffmpeg", "录音", "抽帧", "自媒体", "小红书", "抖音", "B站", "封面图", "口播", "发布", "涨粉", "内容运营", "渲染确定性", "逐帧一致", "Date.now", "随机种子", "重复渲染一致"),
            "tools": "ffmpeg（抽帧/转码） / lab cdp（在线看） / lab ocr（读字幕截图）",
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
        ("E", "渲染确定性契约：禁 `Date.now()` / 未 seed 的 `Math.random()` / 网络请求 / 定时器 / 无限循环（`repeat:-1`）——所有可见内容必须是「时间 t 的函数」", "同一份 HTML 每次渲染出完全一样的帧，才分得清「改坏了」还是「只是随机」；逐帧产出的东西一旦不确定，两次结果就没法比", "要自己管好时间源（统一从 timeline 取 t）；现有代码里藏着的 Date.now() 要逐个清", "连渲两次同一时间点，帧应逐像素一致；不一致就是还有不确定源"),
        ],
    },
    {
        "domain": "编码 / 乱码",
        "words": ("乱码", "编码", "gbk", "utf-8", "bom", "读不出来",
                  "问号", "方块", "字符错乱", "显示不正常", "中文变", "unicode", "转码",
                  "双重编码", "双 BOM", "乱糟"),
            "tools": "lab encoding（判编码） / read hex（看字节） / python 重写",
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
        "words": ("被拦", "安全", "危险命令", "不能执行", "禁止",
                  "拦截", "沙箱", "权限被拒", "拒绝访问", "误删", "红线", "越权", "explain", "规则拦截"),
            "tools": "cc-safety-net explain（被拦先问它） / lab vet（装前）",
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
            "tools": "gh（issue/PR） / lab stage（--repo） / lab commit",
        "routes": [
            ("A", "lab stage + lab commit（发布流水线）",
             "按清单拷贝 + 三层脱敏 + 凭证扫描 + 只重试临时性失败 + 回读校验",
             "只对 repos/dafeiyu-lab 有效，清单要逐文件写；**`lab stage` 的默认 repo 是工作区根**（`tools/lab/lab.py:36`），不写 `--repo repos/dafeiyu-lab` 会把清单里的 57 个文件摊到工作区根 `E:/DS公作区/`并新建 6 个分类目录（2026-11-13 实测 75 个文件，事后要用 trash.ps1 清）",
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
                  "能训", "训得动", "qlora", "Unsloth", "Levanter"),
        # 域级排除（path_options 里：泛词命中才跳过；强词命中时 not_words 不生效）：
        # 治「泛词把别的问题带进来」——「Docker 里怎么设置显存限制」不是本地模型问题。
        # 「内存」进排除词但 3b/7b 在强词里：「内存 32G 能跑 7B 吗」仍命中，
        # 「显存和内存有什么区别」这种纯概念问答不再命中（2026-11-11 用户 m00599 校准）。
        "not_words": ("Docker", "docker", "容器", "虚拟机", "风扇", "内存"),
        # 强词：出现就说明「这就是本地模型问题，只是恰好在容器/虚拟机里跑」，不该被 not_words 挡掉。
        # 2026-11-11 用户 m00599 校准：只测误命中不测漏命中，等于测了一半。
        "strong_words": ("ollama", "qlora", "lora", "本地模型", "微调", "能训", "训得动", "qwen", "3b", "7b", "Unsloth", "Levanter"),
            "tools": "ollama（跑模型） / triage.py（长文本筛） / vision_describe（本地兜底）",
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
            ("H", "升级 Ollama / 换本地模型版本前，先三问：版本差什么、下载得多快、模型目录会不会动（2026-11-14 实测）",
             "①`ollama version` vs GitHub latest 读 release notes，判断改动与本机相关不相关——0.40.16 只改了 Apple Silicon / ARM / Claude 路由，本机 x64+CUDA 一件不沾；"
             "②**大文件先测速再决定**：ollama.com 单连接 14 KB/s、GitHub 16 KB/s、16 并发 88 KB/s（证明是总量限速，不是单连接问题）→ 1.73 GB 要 5.5 小时，不值得；"
             "③模型目录在 `OLLAMA_MODELS=E:\\DS公作区\\cache\\ollama\\models`，升级/重装**不会动模型**，只用重下安装器",
             "官方只发 zip 时别用 zip 覆盖 Inno Setup 装好的目录（runner 版本会错位），用 `OllamaSetup.exe /VERYSILENT`；镜像全挂时不要反复试（本轮 12 个镜像 10 个 000、2 个 403/404）",
             "能说出「升了以后哪条能力真变好、下载要多久、模型要不要重下」——三问答不全就是不该升；升级后三个本地模型各跑一次并与升级前基线对比"),
            ("I", "本地模型接进 DSH：配置里的 contextWindow 只写给 DSH 看，Ollama 按自己的 num_ctx 开窗口（2026-11-18 实测）",
             "`cordis.patch.yml` 里写 `contextWindow: 32768`，DSH 以为能处理 32K；但 `GET /api/ps` 实测 `qwen2.5-coder:7b` 的 `context_length` 是 **4096**（Ollama 默认）——两层各说各话。要真给 32K 必须建自定义模型：Modelfile 写 `FROM qwen2.5-coder:7b` + `PARAMETER num_ctx 32768`，再 `ollama create <新名> -f Modelfile`；实测 32K 版加载 6.4 秒、`size_vram 5.83 GB`、GPU 7605/8188 MiB，8 GB 正好塞下",
             "建了 Modelfile 却不改配置里的 model id，UI 里选的还是原来那个 4096 的；`ollama create` 产出的新模型是独立条目（`qwen2.5-coder-32k:latest`），列表里会同时存在两个，容易选错",
             "`curl -s http://localhost:11434/api/ps` 里该模型的 `context_length` 等于你配的数，不是 4096"),
            ("J", "本地模型能不能替代官方 API，先算「messages + tools[]」两笔账装不装得下——不是「模型能不能跑」（2026-11-18 实测三轮）",
             "DSH 每次请求实际发两样东西：**messages ~25K tokens**（identity.md 1,511 字符 + user.md 1,938 + assets.md 1,167 + 记忆注入 36,261 字符 + 历史）+ **tools[] ~22K tokens**（每个工具的完整 JSON Schema，不是名字）。合计 **47K**。bili 的 preflight guard 用 `measuredOutbound()` 分四桶（messages/tools/system/other）校验，超窗口直接 413 `preflight_compress_failed`、**根本不发给模型**。实测三轮日志：`25,029 + 21,980 = 47,014` / `25,016 + 21,642 = 46,663` / 异常一轮 `84,680 + 551 = 85,236`。8 GB 显存最多 32K 窗口，不够",
             "「模型能加载」和「能跑 DSH 的完整对话」是两件事；**tools[] 那 22K 是我原来漏算的**，光砍 messages 救不了（20K + 22K = 42K 仍 > 32K）；第一次那 84,680 是工具未加载完的异常值，别拿它当基准",
             "能说出「47K 里 messages 和 tools 各占多少」并承认 32K 窗口下这条路走不通；要本地当会话模型得 ≥64K 窗口 + ≥12 GB 显存（7B 的 64K KV cache 约 7 GB，加模型 4.76 GB 已超 8 GB）"),
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
                "路线库", "候选路线", "体检", "整理路线", "维护路线", "自检",
                # 2026-11-14 补：接需求五类公式（读清华 PDF 吸收），补触发词。
                "提需求", "需求公式", "五类需求", "把需求说清楚", "需求没说明白",
                # 2026-11-15 补：写/审技能文件（skill.md 六段结构，读清华 OpenClaw 报告吸收）。
                "技能文件", "SKILL.md", "skill.md", "技能说明", "写技能", "审查技能", "学习路线",
                # 2026-11-17 补：`lab log` 的触发词（体检报告说它 98 次调用、路线库只提 1 次）。
                "决策日志", "留个记录", "为什么这么做", "记一笔", "留痕", "留个理由",
                "加路线",
                "补触发词",
                "补词",),
            "tools": "edit（SKILL.md/规则） / lab selfcheck（改完验） / lab commit",
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
           "五组全 0 处不一致 + lab health --force 无假域（2026-11-15 修：这里原来只写 route_health 文件名，"
           "结果「高频低权」表把 lab health 记成 0 次提及——可直接执行的命令才算验收动作）；"
           "再拿用户最可能说的那句话跑一次 lab tier，命中落在预期域且新路线出得来"),
          ("I", "接需求先归五类（决策 / 分析 / 创作 / 验证 / 执行），按公式补齐缺失项",
           "清华《DeepSeek 从入门到精通》P17 的五类需求公式（教学材料，非官方；我 2026-11-14 读后吸收）："
           "决策 = 目标 + 选项 + 评估标准；分析 = 问题 + 数据 + 分析方法；"
           "创作 = 主题 + 风格/约束 + 创新方向；验证 = 结论/方案 + 验证方法 + 风险点；"
           "执行 = 任务 + 步骤约束 + 输出格式。"
           "用户一句话里常缺一两项（「选哪个好」没给评估标准、「帮我分析下」没给数据），"
           "缺的那项要么问、要么按他的目标自己补并说明「我按 X 补的」",
           "分类是辅助不是枷锁：一句话可能混合两类（「分析完再帮我写报告」），别硬塞；"
           "也不能拿它替代真实澄清——缺的是关键信息时该问还是要问",
           "动手前能写出一行「他的需求 = 哪一类 + 缺哪几项 + 我怎么补的」；"
           "写不出就是没听懂需求，先别动手"),
          ("J", "写/改 SKILL.md 或技能说明时，按 skill.md 六段检查：名称与简介 / 适用场景 / 输入与前提 / 执行步骤 / 工具与限制 / 输出要求",
           "清华《OpenClaw 在媒体中的应用-实操版》(2026-03, 何静/沈阳团队) p4 的定义：skill.md 是给模型或自动化代理看的说明文件，定义某个技能该怎么触发、怎么执行、要遵守什么规则。六段：①Name 技能名称 ②Description 功能说明 ③Trigger 触发条件 ④Workflow 执行流程（需要哪些资料/文件/条件）⑤ToolConstraints 工具限制（能用什么、不能做什么）⑥Output 输出要求（格式/风格/注意事项）。"
           "对照我的 workflow SKILL.md：名称=frontmatter name、简介=description、适用场景=description+§0、输入与前提=§0.2 那张表、执行步骤=§4 流程、工具与限制=§5.1 工具表+§0 禁区、输出要求=§0 第 3 条「只列异常」",
           "这是别人（OpenClaw 生态）的约定，不是我已有的强制结构——套用前先判断缺的那段是真缺还是换了个名字存在；六段是检查表不是模板，别为凑段数把技能写长",
           "写完/审完能逐段指出「这段在第几行、没有的段为什么不需要」；缺 Output 段 = 产出格式没人约束，缺 ToolConstraints = 容易越权"),
            ("K", "写给自己（或任何 agent）看的文档，逐句过「no-op 测试」和「否定式检查」：模型默认就会遵守的指令删掉；把「不要 XXX」改成说正向目标",
             "常驻上下文的每个字每轮都付费，no-op 是纯浪费；否定式会把被禁行为拖进上下文、让它更可得（「不要想大象」满脑子都是大象），正向表述才把注意力放到该做的事上",
             "no-op 判据是模型相对的、不是读者相对的——两个人都觉得「这是废话」也可能都错，只能跑一下文档看行为有没有变；删一句话比改十句话省事",
             "删掉一句话后行为没变 = 它是 no-op；「不要」开头的句子数应该在下降；改完能用同一份材料跑出同样的行为"),
            ("L", "重要决策留一份理由：`lab log --mark <标识> --title \"<一句话>\" --body-file <文件>`",
             "正文四小节：做了什么 / 为什么 / 取舍 / 教训。`--mark` 同时做幂等判断（同标识不重复写）；"
             "`--tail N` 看最近几条历史（**`--list` 不存在**，别试）。"
             "治的是「几周后没人记得为什么这么做」——代码能看出做了什么，看不出取舍理由",
             "要写四小节，没想清楚就写不出来；它不是备忘录，是给未来的人（包括下一个我）看的",
             "`lab log --tail 3` 能看到本轮条目；`lab selfcheck` 的决策日志组应仍全绿"),
          ("M", "`lab route add`：加路线 + 补触发词一次做完（AST 定位 / 写前校验 / 读回）",
           "这周手工补库 20+ 次，同一位置反复出三类错：只加 routes 不补 words（至少 4 次空命中）、words 折行切掉右括号、全角引号/长缩进锚点匹配失败。这条命令用 AST 找域和列表边界，不靠字符串锚点；五元组和 words 一次写入；写前 py_compile + 载入校验（域数不变、路线 +1、新词进 words），写后读回 path_options；默认必须给 --word，--no-words 才能跳过；失败一个字不写，改前有备份",
           "只能追加，不能改/删已有路线；长文本一行一条，diff 不如手工排版；读回用新词，不代表用户原话一定命中；改完仍要跑 lab test + 重建基线 + lab selfcheck（工具不替你做这三步）",
           "`lab route add ... --dry` 先看预览；真加后 `lab route list --domain <域>` 看到代号和词数 +1；`lab test` 197+ 全绿；`.tmp/tier-baseline.py` 重建后 `--check` PASS；`lab tier <用户原话>` 能看到这条代号"),
        ],
  },
    {
        "domain": "下载 / 网络 / 换源",
        # 2026-11-07：补 4 个词。用户说的是「Ollama 升级 / 装个新版本」，一个词都不在
        # 原 words 里，所以「下载域」压根没被命中，跨域链也就出不来。
        # 没加裸词「升级」（「升级 lab 的测试」会被误命中），只加带软件/渠道语义的。
        "words": ("下载", "安装包", "镜像", "换源", "拉取", "网速", "吞吐", "断网", "代理", "winget", "升级包", "版本升级", "Ollama", "release", "ghfast", "直连", "wheel", "本地装", "--no-index", "pip 慢", "装包卡住", "pip 卡住", "抓不到", "抓不下来", "被拦", "反爬", "403", "451", "空内容", "网页打不开", "打不开网页", "封了", "读不了"),
            "tools": "lab dl（下载唯一入口：选源->测速->判断->下并校验） / lab nettest（只测速不下载） / curl / npm registry",
        "routes": [
            ("AA", "要下任何东西：`lab dl <url…> [-o 路径] [--max-minutes N]`（三步一次做完）",
             "把「选源 + 测速 + 判断要不要继续」合成**一条命令**：多源各下 8MB 落盘量真实字节算速度，"
             "排名后按「总大小/实测速度」估时间，**超预算 exit 3 停下问**，不超才下且下完校验字节数。"
             "2026-11-18 建，起因是用户 m11537 说我「手写 curl 试五个源花 20 分钟、BtbN 下到 47.2MB 断了 152MB」"
             "——判据是**只要准备敲 curl/wget 下一个没测过的东西，就是跳过了它**",
             "单源也要跑（它替你做「值不值得等」的判断）；探针各下 8MB，第一次约 1–2 分钟；"
             "`--max-minutes` 给太小会立刻 exit 3（这是设计不是 bug）",
             "输出末行 `[OK] <路径> <大小> <秒> <速度>` 且 exit=0；超预算时 exit=3 且**目标文件与 .part 都不该存在**"),
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
            ("I", "「大文件下不动」先判是单连接慢还是总量限速，再决定要不要继续折腾（2026-11-14 实测）",
             "①单连接测速（`curl -r 0-1048575 -o NUL -w '%{speed_download}'`）→ ②16 并发各下 1 MB → "
             "两相比较：并发只快 3-6 倍说明**带宽是总量上限**，镜像再多也救不了，该判「不升/改天/换网」而不是继续换源；"
             "③顺带把候选镜像各测 8 秒（本轮 ollama.com 14 KB/s、GitHub 16 KB/s、gh-proxy 35 KB/s、fastgit 25 KB/s、其余 12 个 000/403/404）",
             "测速本身要花 token 和时间；`-r 0-1048575` 有的 CDN 不支持 Range 会退化成整下；判「不升」要给用户替代选项（代理/网盘/等官方包）",
             "能给出「预计要多久、为什么换源没用、现在有什么替代路径」三个数字/选项，而不是「我再试试」"),
            ("J", "pip / npm 装包卡住：先用 curl 下一个 wheel 对照测速（2026-11-17 实测差 100 倍）",
             "同一条 `https://pypi.tuna.tsinghua.edu.cn/packages/.../click-8.5.1-py3-none-any.whl`：`curl.exe -sL -o x.whl` 0.9 秒下完 126 KB，`pip install click` 花了 97.9 秒——**慢在 pip 的联网/解析层，不是网速**。判据：装包超过 3 分钟没进展，立刻 curl 一个同源 wheel 计时；差 10 倍以上就改走「curl 下 wheel → `pip install --no-index --progress-bar off @files` 本地装」",
             "本地装要求所有传递依赖的 wheel 都在同一目录，缺一个就报 `Could not find a version that satisfies the requirement X (from versions: none)`（要用 PyPI JSON 的 `urls[].url` 逐个补）；PowerShell 通配符不展开，必须 `$files = (Get-ChildItem $dir -Filter *.whl).FullName` 再 splat 成 `@files`",
             "装完 `pip list` 能看到目标包 + `python -c \"import 包名\"` 不报错；判进度看这两条，不看 job 状态"),
            ("K", "大文件下到一半网断了：Stop-Process 保 -partial，换网络后从断点续传（2026-11-18 实测）",
             "`ollama pull qwen2.5-coder:7b` 速度掉到 600 KB/s 时用户切手机热点；`Stop-Process -Id <pid>` 直接关掉，`-partial` 文件留在 `E:\\DS公作区\\cache\\ollama\\models\\blobs\\` **不会被删**；`Start-Process ollama pull` 重新拉起后从 64% 续传，速度 2.7 MB/s（快 4.5 倍），9 分钟下完 4.7 GB",
             "别用 `Start-Job` 起（会话结束 job 就没了，见 mem_mwkpudg6_tqunmf），要用 `Start-Process` 起独立进程；`ollama pull` 幂等，重跑不会从头开始，但目标名写错会另下一份",
             "`ollama list` 里出现完整模型且大小对得上（7B 是 4.7 GB）"),
            ("L", "本机抓不下来：`deepseek_read_url`（官方服务端抓，备用不是默认）",
             "只在 Scrapling / `web_fetch` 返回 **403 / 451 / 空内容**时考虑——这类失败多半是**网络位置差异**"
             "（对方封了你的出口 IP），本地换 UA、加代理都不一定绕过。"
             "**但它能抓的域名比想象中窄**：2026-11-19 实测 `raw.githubusercontent.com` 直接被拒"
             "（模型回「当前检索范围不支持访问」），`example.com` 只拿到 title、正文 `data` 是空串",
             "要钱：**0.005 元/次**（`usage.server_tool_use.web_fetch_requests` 计数，实测 1 次）；"
             "响应比普通回复多两个 block type（`server_tool_use` / `web_fetch_tool_result`），"
             "后者带 **约 1.5 KB base64 `signature`**；**DSH 目前两种都不认识**"
             "（2026-11-19 查 asar：`deepseek_read_url` 0 处命中）。抓不到时给的是 **`content: null`** 不是报错，"
             "模型会照实说「我读不到」——这点比编造强，但也意味着它帮不上忙",
             "curl 一次带 `tools:[{\"type\":\"deepseek_read_url\",\"name\":\"deepseek_read_url\"}]` 的请求，"
             "看 block 顺序是不是 `thinking→server_tool_use→web_fetch_tool_result→thinking→text`；"
             "`lab tier \"本机 IP 抓不到某个站，怎么办\"` 应命中本域并打印 L 条"),
        ],
    },
    {
        "domain": "科学计算 / 数值模拟 / 数据分析",
        "words": ("模拟", "仿真", "蒙特卡洛", "数值", "计算", "统计", "概率",
                  "矩阵", "积分", "微分", "求解", "拟合", "科学计算",
                  "numpy", "scipy", "pandas", "数据分析", "实验数据", "数据库", "索引"),
        # 2026-11-13 补（机制同「本地模型」域，先例在那边）：误命中活例——
        # 「批量跑一遍lab子命令做冒烟统计成败」被裸词「统计」拖进本域（demo-tier2 实录）。
        # 泛词命中 + 排除词 → 这是自检话题不是数值计算；强词（真算数）出现时不排除。
        "not_words": ("冒烟", "批量", "自检", "子命令", "成败"),
        "strong_words": ("蒙特卡洛", "仿真", "numpy", "scipy", "pandas",
                         "数值", "拟合", "矩阵", "科学计算", "实验数据", "数据库", "索引"),
            "tools": "python（numpy/pandas，用 load_workspace_dependencies 拿路径） / lab blender（可视化）",
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
                  "暂存", "stage", "撤销", "回滚改动", "改前先看", "上一个改的", "谁动过", "别人改了什么"),
            "tools": "git / lab commit（含 bundle 备份） / lab reconcile",
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
            ("F", "`lab commit`（提交默认走它，不手敲 git commit）",
             "自动带「日期 + 机器 + 任务」头部、跑排版自检；中文 message 用 `--msg-file`（UTF-8 无 BOM）"
             "避开 PowerShell 引号坑；2026-11-14 实测提交 8c94ee2 一次过",
             "默认只提交已跟踪改动；新文件要 `--all` 或 `--files`；`--no-push` 才是纯本地",
             "`git log -1 --stat` 的改动清单 == 本次要交的文件；被 selfcheck 拦时先修机制再提交"),
        ("G", "改别人的文件之前先 `git log --oneline -5 -- <file>` 看最近谁动过、为什么", "避免「我刚定的标准是新的，其实团队上周已经统一过口径」；也是接手旧稿时唯一能看出「这段为什么这么写」的入口，比通读代码快", "只对进过版本库的内容有效；未提交的改动看不到理由", "改文件前跑一次，能说出「上一个改它的人想解决什么」才算看过"),
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
            "tools": "gh issue/pr / lab issue / lab review",
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
                  "读一遍", "读这个文件", "源码", "读透", "核心模块", "移植实现", "读懂实现", "测试", "上游测试", "tests",
             "asar", "安装包里的代码", "包内", "内置包", "装包里", "库的设计", "怎么读"),
            "tools": "lab lsp（符号） / grep（定位） / lab asar（读打包代码）",
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
             "npm 包通常不带 tests，要去 GitHub 取——`raw.githubusercontent.com` 有时能取有时不能（hookable 能、ofetch 不能），`api.github.com` 走 ghfast.top 镜像报 Invalid input，**兜底用 jsDelivr 的 gh 通道**（`cdn.jsdelivr.net/gh/<owner>/<repo>@<tag>/<path>`；列目录用 `data.jsdelivr.com/v1/packages/gh/<owner>/<repo>@<tag>?structure=flat`）",
             "同一套用例跑原版与重写，行为（事件序列 / 同步还是 Promise / 错误消息 / 警告次数）逐条一致"),
            ("G", "`lab asar list|desc|read`（读装包里的真实代码，判断某个键/包在不在）",
             "DSH 装的是 app.asar，配置项和内置 bundle 到底存不存在只能问它：`list <关键字>` 看包、"
             "`desc` 看版本、`read <包内路径>` 直接读源码；2026-11-14 用它确认 `dsh-plugin-desktop` 在 asar 内 0 次、"
             "forge 系列已内置",
             "只读，解析的是当前安装的版本；包内路径要按 `/dsh/node_modules/...` 写；大文件用 `--max` 截断",
             "能说出「这个名字在 asar 里出现 N 次 / 路径是 X」；拿不到就是版本不对或路径写错"),
        ],
    },
    {
        # 2026-11-08 新增：同上。提了 PR 不等于完事，得能跟到最后。
        "domain": "长期跟踪 / 外部反馈",
        "words": ("跟踪", "后续", "反馈", "订阅", "轮询", "被拒", "拒了", "关闭",
                  "合并", "状态", "观察", "持续关注", "等一下", "过几天", "等回复"),
            "tools": "lab journal（记） / lab review（复盘） / gh pr list（看被拒/被晾）",
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
            "tools": "lab now（当前） / lab since（间隔） / lab session-age（会话年龄）",
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
            ("E", "`lab since 11-14` / `lab now`（说时间之前先拿数字）",
             "`lab now` 给当前时刻 + 计费时段；`lab since 11-14` 给「从那天到今天」的准确天数——"
             "2026-11-08 实测 19 天，我凭印象说 18 天是错的",
             "since 只接受 `YYYY-MM-DD` 或 `MM-DD`；算「两件事隔多久」要跑两次或自己减",
             "输出日期与手数一致；**说「昨天/上周」前必须先跑它**——没有数字就不许写时间词"),
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
                  "UAC", "后台跑", "僵尸进程", "常驻", "窗口标题", "当前会话", "看的是哪个", "job running", "进程还在", "没跑完", "后台任务状态", "查副作用", "running", "job 状态", "做没做完", "没做完"),
            "tools": "lab tasks（任务结果码） / Get-CimInstance Win32_Process（进程命令行） / lab desktop（窗口）",
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
            ("E", "拿窗口标题当「当前 UI 状态」探针（2026-11-14 实测）",
             "桌面端窗口标题就是当前打开的会话名（`大肥鱼-6 — DeepSeek Harness`）；"
             "`(Get-Process | ? MainWindowTitle -like '*DeepSeek*').MainWindowTitle` 一条命令、约 1 秒，"
             "比截图+读图快得多——点完/切完立刻用它确认落点",
             "只对「标题里带状态」的程序有效（浏览器标题是页面标题，也有效）；"
             "标题可能滞后几百毫秒，点完要等一下再读",
             "命令输出直接等于期望的会话名/页面名，才算状态切换成功"),
            ("F", "「进程还在」≠「事情没做完」——查副作用，不看 job 状态（2026-11-17 一天踩两次）",
             "`pip install scrapling` 后台 job 跑 20 分钟一直 running，我看状态就判「没装上」，实际 `pip list` 里早有了；`pip download lxml` 同样，文件 3.82 MB 早已落盘完整（mtime 对得上）。**根因**：PowerShell 的 `& cmd | Select-Object -Last N` 和 `Start-Process -RedirectStandardOutput` 都会让子进程输出管道不关闭 → 进程不退出 → job 管理器只看进程在不在",
             "要写对「查哪条痕迹」：装没装上查 `pip list`、下完没下完查 `ls` 的字节数+mtime、提交没提交查 `git status`、跑完没跑完 grep 产物；进程状态只当参考。反向同样成立——**进程退出不代表成了**（`exit 0` 但输出为空、或 `Measure-Command` 吞掉了 pip 的 stderr，都要当失败）",
             "判断依据是副作用（包/文件/提交/产物文件）而不是 job 或进程状态；**判据只走命令返回的布尔值**（`Select-String -Quiet` / `grep -c` / `pip list | Select-String`），不靠眼睛在输出片段里找——2026-11-17 同一天第三次误判就是 `Select-Object -Skip 30 -First 45` 截断输出后判 `lab tier`「没命中」，实际 F 条标题行一直在第 46 行之后、折叠提示也一直在；汇报时能指名「我查的是哪条痕迹」"),
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
                  "把图变成模型", "把图片变成模型", "一张图变",
                  # 2026-11-14 补：读清华《DeepSeek 从入门到精通》后吸收「推理 vs 通用模型问法差异」，
                  # 先补 words 再补路线——只加路线不加词会空命中（11-14 已经在这个坑上栽过一次）。
                  "推理模型", "通用模型", "思考模式", "深度思考", "思维链", "step by step"),
            "tools": "config（patch 里加模型） / lab nettest（先测通） / curl（探 /models）",
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
            ("L", "推理模型和通用模型要换问法：推理模型给目标+约束，通用模型给结构+例子",
             "清华《DeepSeek 从入门到精通》P13–P18 的核心（教学材料，非官方；我 2026-11-14 读后吸收）："
             "推理模型（R1 / o3 / qwen3.8-max 思考模式）自带思考链，再给「第一步第二步」会干扰它，"
             "要的是「问题 + 边界 + 判据」；通用模型（chat 模式 / 小参数模型）不会自己想，"
             "要给结构、给步骤、给示例。两边都适用的只有「说清要什么」这一件事",
             "这是「写指令」的差异，不是「模型好坏」；DSH 里 system prompt 结构固定，"
             "这条主要用在①接新 provider 时写验收 prompt ②给用户解释某个模型该怎么用 "
             "③本地小模型（3b）必须傻瓜指令、大模型只要目标",
             "验收 prompt 同一句走两个模型：推理模型不该出现「按你说的步骤」这种回声，"
             "通用模型不该跳步；出现任一说明问法给错了"),
        ],
    },
    {
        "domain": "系统建模 / 结构化理解",
        "words": ("建模", "系统建模", "领域建模", "数据流", "dfd", "c4", "上下文图",
                  "容器图", "组件图", "限界上下文", "聚合", "实体", "抽象",
                  "结构理解", "架构图", "分层", "画图", "系统结构", "测绘",
                  "系统模型", "数据模型", "领域模型", "resolve", "声明意图", "按意图找", "解析资源"),
            "tools": "archify skill（画图） / write（成文）",
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
        ("F", "声明意图让系统解析资源：`resolve --type <类型> --intent '<一句话需求>'`，而不是先枚举再挑", "需求含糊时先声明「我要什么类型、用来干什么」，由系统解析到具体资源并回报落点与元数据；比「先列清单再人工挑」少一轮来回，也不会因为清单太长而随手挑一个", "需要系统这边真有解析层；纯手工目录结构用不上", "跑一次 resolve，看它是否打印 `resolved <id> -> <path> (<type>)`；打印不出就是没有解析层"),
        ],
    },
    {
        "domain": "DSH 界面显示 / 配置项（界面上某块不见了）",
        "words": ("界面", "看不到", "不见了", "面板", "用量", "缓存命中", "设置页", "入口",
                  "ui-chat", "ui-settings", "显示不对", "没有显示", "按钮没了", "面板没了"),
            "tools": "cordis.patch.yml（改配置） / env_doctor（查状态） / lab config（读配置）",
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
            "tools": "config（预设） / lab config（当前值）",
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
    {
        "domain": "硬件 / GPU / 本机资源（显卡、显存、温度、驱动）",
        "words": ("显卡", "GPU", "显存", "RTX", "独显", "核显", "显卡驱动", "驱动版本",
                  "风扇", "温度", "功耗", "帧数", "跑分", "爆显存", "显存不足",
                  "内存够不够", "硬盘够不够", "虚拟机", "装驱动", "回滚驱动",
                  "笔记本", "散热", "过热", "降频", "硬盘", "装系统", "容量够不够"),
            "tools": "nvidia-smi（显存/温度/功耗） / Get-CimInstance Win32_VideoController（双卡） / read_image（看截图）",
        "routes": [
            # 2026-11-15 实测：本机是双显卡笔记本（AMD 780M 核显 + RTX 4060 Laptop 独显），
            # 16 GB 内存。用户问过十几次显卡问题（温度/功耗/帧数/显存），路线库里却一条都没有
            # ——不是不会答，是没把「硬件排查」当成能力记下来。
            ("A", "先读真实硬件状态，别信 WMI 的显存数",
             "`nvidia-smi --query-gpu=name,memory.total,memory.used,temperature.gpu,power.draw,driver_version --format=csv` "
             "一条命令出全表；本机实测 RTX 4060 Laptop：8188 MiB / 已用 1001 MiB / 50°C / 12.15 W / 驱动 565.90",
             "**WMI 的 `Win32_VideoController.AdapterRAM` 对 >4GB 显存报不准**——32 位字段溢出，"
             "本机 8GB 被报成 4096 MB（2026-11-15 实测）；设备管理器只显示型号不显示真实显存；"
             "`nvidia-smi` 不在 PATH 里时要写全路径 `C:\\Windows\\System32\\nvidia-smi.exe`",
             "型号 / 显存 / 驱动三个数字都来自 `nvidia-smi`；与 WMI 的 `AdapterRAM` 对不上时以 nvidia-smi 为准"),
            ("B", "双显卡笔记本：先确认任务跑在哪张卡上",
             "本机 AMD Radeon 780M（核显，驱动 32.0.12011.1036）+ NVIDIA RTX 4060 Laptop（独显）；"
             "CUDA / Ollama / Blender Cycles 默认走独显，但浏览器、视频解码、DX 游戏可能走核显",
             "两套驱动各自更新、互不替代；核显驱动由 Windows Update 管，独显驱动要去 NVIDIA 官网；"
             "`nvidia-smi` 的 GPU Memory 栏没有 PID 只说明没进程在用独显，不等于任务没跑",
             "`nvidia-smi` 里能看到目标进程的 PID 与显存占用才算走独显；否则去显卡控制面板或 BIOS 改默认 GPU"),
            ("C", "温度 / 功耗 / 风扇：分三档判，不看感觉",
             "待机 <55°C、轻载 55–75°C、持续负载 <85°C 算正常；>90°C 持续 = 散热问题（清灰/换硅脂/降功耗墙）；"
             "风扇声音大先看转速是否与温度匹配（`nvidia-smi -q -d FAN`）",
             "笔记本的功耗墙和温度墙联动——降功耗墙能压温度但掉性能；"
             "「感觉变热了」不是判据，同一负载下前后两次的数字才是",
             "同一负载（同一游戏 / 同一模型）下两次 `nvidia-smi` 的温度与功耗对比；"
             "满转但温度低 = 风扇曲线问题，不是散热问题"),
            ("D", "显存 vs 内存：先分清哪个不够",
             "显存不够 = 爆显存（`CUDA out of memory` / OOM / 画面撕裂）；内存不够 = 卡顿、页面文件飙高、系统假死；"
             "本机 8 GB 显存跑 7B 4-bit 约 4.5–5 GB 够，14B 4-bit 约 9–10 GB 不够；16 GB 内存跑虚拟机建议给 4–8 GB",
             "两个数字容易混：显存看 `nvidia-smi` 的 memory.total，内存看 "
             "`Win32_ComputerSystem.TotalPhysicalMemory`；核显会共享系统内存（本机 780M 分走 0.5 GB）",
             "能说出「哪个不够」对应的具体症状 + 两个数字的来源，而不是笼统说「配置不够」"),
            ("E", "驱动问题分三类：不识别 / 花屏 / 帧数低",
             "不识别或花屏 → 设备管理器卸载设备（勾删除驱动）后重装；帧数低 → 先查是不是走了核显再查驱动；"
             "新驱动出问题 → 设备管理器「回滚驱动程序」或 DDU 干净卸载",
             "笔记本显卡驱动别直接装 NVIDIA 官网的桌面版——要用厂商（华硕/联想）定制版或带笔记本标记的版本；"
             "DDU 要进安全模式；回滚前记下版本号 + 日期",
             "设备管理器里显卡无黄色感叹号 + `nvidia-smi` 能出表 + 帧数回到基线（记下改前改后两个数）"),
            ("F", "跑重活前看 GPU 占用，别和用户抢",
             "用户 2026-11-07 定的红线：GPU 占用 90%；跑模型/渲染前先 `nvidia-smi` 看一眼，"
             "用户游戏或剪辑开着就让，等他不用了再跑",
             "Ollama 加载模型会一次性吃满显存，跑完不卸载会一直占着（`ollama ps` 看，`keep_alive=0` 让它卸载）；"
             "Blender Cycles 默认吃满所有 GPU",
             "跑之前看 `memory.used` 与 GPU 利用率；跑完 `ollama ps` 应显示已卸载或按需卸载"),
            ("G", "框架说「CUDA 版本太低 → 性能会很差」= 驱动版本不够，不是驱动坏了",
             "2026-11-16 实测：ComfyUI 启动日志报 "
             "`WARNING: PYTORCH CUDA VERSION BELOW 13.0 … Performance will be terrible`，"
             "当时驱动 565.90 只支持到 CUDA 12.7，框架退回 eager 路径 → 出图 7 分 32 秒；"
             "换驱动 621.24（CUDA 13.0）后同一张图 38.3 秒，**快 11.7 倍**",
             "①这种慢是「性能降级」不是「跑不起来」，最容易误判成模型太大 / 显存不够 / 显卡不行；"
             "②NVIDIA 安装器不兼容中文路径——只要安装目录含中文，进程根本不出现，先复制到 `C:/Windows/Temp` 再执行；"
             "③装驱动前必须关掉占 GPU 的进程（框架占着显卡会让安装器**静默退出**：不报错、不留日志、版本不变）；"
             "④装完要重启，`nvidia-smi` 右上角 CUDA Version 才会更新",
             "`nvidia-smi` 右上角的 CUDA Version ≥ 框架要求的版本；框架日志里不再出现「VERSION BELOW」警告；"
             "同一个任务耗时回到基线（记下改前改后两个数，别只看「快了」）"),
        ],
    },
    {
        "domain": "磁盘空间 / 清理 / 迁移",
        "words": ("磁盘满了", "C盘满了", "磁盘空间", "空间不够了", "清理磁盘", "清理C盘",
                  "释放空间", "回收站", "删了没变", "空间没变", "迁移", "挪到别的盘",
                  "junction", "符号链接", "硬链接", "C盘红了", "可用空间", "占用太大",
                  "哪些文件大", "删不掉", "空间去哪了", "少了10个G", "腾空间",
                  "两个版本", "装了两个", "旧版本", "重复安装", "旧版能不能删",
                  "腾点空间", "腾出空间", "清一清磁盘"),
        "tools": ("pwsh", "E:/DS公作区/tools/trash.ps1"),
        "routes": [
            ("A", "先算账：哪些目录真占地方，别凭印象",
             "`Get-ChildItem <盘>:\\ -Directory -Force -EA SilentlyContinue | ForEach-Object { "
             "[PSCustomObject]@{N=$_.Name; MB=[math]::Round((Get-ChildItem $_.FullName -Recurse -File "
             "-Force -EA SilentlyContinue | Measure-Object Length -Sum).Sum/1MB,1)}} | Sort MB -Desc | "
             "Select -First 15` —— 一次扫出真实占用，再决定删什么",
             "递归扫整盘要几十秒到几分钟；权限错误靠 `-EA SilentlyContinue` 跳过，别让脚本中断；"
             "「用户说少了 10 GB」和「实际找到 8.4 GB」对不上是常态，差额在系统保留/还原点里（见 F）",
             "能列出 top 15 目录 + 每个的真实 MB + 合计，且合计与「磁盘 Free 变化」量级对得上"),
            ("B", "进回收站 ≠ 释放空间，必须清空才算",
             "`E:/DS公作区/tools/trash.ps1` 把文件移到 `$RECYCLE.BIN`——文件只是换了个地方存，磁盘 Free 一点不变。"
             "要真释放：`Clear-RecycleBin -DriveLetter C,E -Force`（2026-11-16 实测 C +2.34 GB / E +5.52 GB）",
             "①清空不可恢复，但回收站里的东西本来就是打算删的；"
             "②`Clear-RecycleBin` 有时报「cannot find the file specified」却仍然释放了，别看报错以为失败；"
             "③先用 `Shell.Application.Namespace(0xA).Items()` 数一下项数再清，知道自己在清什么",
             "清空前 `Get-PSDrive C` 的 Free，清空后再看，差值应该 ≈ 回收站大小（记下两个数）"),
            ("C", "大目录迁到别的盘：robocopy → 校验 → 删原 → mklink /J → 验证",
             "`robocopy <src> <dst> /E` 复制（实测 2.5 GB / 58 文件 2 秒）→ 核对文件数与总大小 → "
             "`Remove-Item <src> -Recurse -Force` → `cmd /c mklink /J <原路径> <新路径>`",
             "①junction 只对目录有效，单文件要 `mklink /H`；②目标盘必须 NTFS（FAT32/exFAT 不行）；"
             "③有些程序出于安全会拒绝跟随 junction；④**DSH 重装 runtime 会覆盖链接**，记录在案；"
             "⑤删原目录前必须校验复制完整，否则两头都不全",
             "`Get-Item <原路径> -Force` 的 Attributes 含 `ReparsePoint`、Target 指向新路径；"
             "再跑一次依赖它的命令（如 `python -c \"import torch;print(torch.cuda.is_available())\"`）确认能用"),
            ("D", "双版本软件：查注册表真版本，删旧版",
             "WPS / Office / Docker 升级后常留旧版本目录（如 `WPS Office\\12.1.0.29161` 和 `29690` 各 1.4 GB）。"
             "查 `HKCU:\\Software\\Kingsoft\\Office\\6.0\\common` 的 InstallRoot / Version 看哪个是活的，"
             "再对照运行中进程的 exe 路径，删掉旧的那个",
             "①WPS 有 `EnableClearOldVersions: false`（默认不自动删旧版），所以会一直并存；"
             "②删前确认进程不在跑；③别只看目录 mtime——升级可能只改注册表不改目录时间",
             "注册表 Version == 保留目录名；运行中 `wps.exe` 路径指向保留版本；旧目录已进回收站"),
            ("E", "DISM 清 WinSxS：分析报的数字多半是硬链接，删了不释放",
             "`dism /Online /Cleanup-Image /AnalyzeComponentStore` 会报「备份和已禁用的功能 X GB、推荐清理 是」，"
             "但 2026-11-16 实测跑完 `StartComponentCleanup`（不加 `/ResetBase`）后 WinSxS 仍 8880 MB、"
             "磁盘 Free 一点没变——那 X GB 主要是与 system32 共享的硬链接，删掉不算真实回收",
             "加 `/ResetBase` 会清掉所有旧更新备份，以后无法卸载更新，风险高（本机没加）；"
             "这条路只值得在「其它地方都腾不出空间」时试一次，别当主力",
             "跑前跑后各记一次 WinSxS 大小 + 磁盘 Free，如实报告「释放了多少」（这次是 0）"),
            ("F", "先分清是「文件占的」还是「系统保留的」",
             "用户问「怎么少了几 GB」时，除了目录还要盘系统占用：保留存储、页面文件、休眠文件、系统还原点、"
             "回收站本身都不在普通目录里。查法：`vssadmin list shadowstorage`（还原点）、"
             "`Get-Item hiberfil.sys -Force`（在 C 盘根跑，看休眠文件）、`Get-Volume C`（Free vs Size）、"
             "`dism /Online /Cleanup-Image /AnalyzeComponentStore`（WinSxS）",
             "①关休眠（`powercfg /h off`）会丢快速启动；②删还原点会失去回滚能力；"
             "③WinSxS 不能手删；④保留存储（Reserved Storage）在设置里读不到精确值",
             "能说出「这 X GB 的构成」：普通文件 / 还原点 / 休眠文件 / 保留存储 各占多少，而不是只说「系统占了」"),
        ],
    },
    {
        "domain": "能力成长 / 学新东西",
        "words": ("学习", "学新的", "不会", "怎么学", "练手", "掌握", "能力成长",
                  "成长路径", "学一门", "上手", "熟悉", "入门", "补短板", "技能",
                  "学会", "还不会", "从零学", "该怎么练", "练熟", "学不下去",
                  "没人教", "自学", "怎么进步", "能力不够",
                  "学一个新的", "想学", "要学", "该学什么", "从哪开始学",
                  "练不好", "练不会", "学不会", "学不懂", "学得慢",
                  "提升", "改进", "优化一下", "变强", "更强", "怎么变好",
                  "缺陷", "短板", "不如", "比不过", "怎么提高"),
        "tools": ("E:/DS公作区/自进化/路线图.md", "E:/DS公作区/学习计划", "lab tier"),
        "routes": [
            ("A", "先定「学完要能交付什么」，再找资料",
             "从目标反推产出：比如学 Blender 的目标不是「看完教程」，是「能建出一个可交付的场景」；"
             "学爬虫不是「读懂 requests 文档」，是「能把某个站的数据完整抓下来存成文件」。"
             "产出定下来之后，资料才筛得动——不合这个产出的先不看",
             "产出设计本身要花时间；而且一开始往往定不准，学到一半要改",
             "能一句话说出「学完这件事，我要交付的具体东西是什么」；说不出就是还没想清楚，先别开始看资料"),

            ("B", "判断「是不是真会了」：关掉教程从零复现一遍",
             "不看「看了多少」，看「能不能独立做出来」。具体做法：合上教程、清空状态，"
             "只凭自己的理解把上次那个东西再做一遍；卡在哪一步，哪一步就是没学会的",
             "复现比跟着做慢得多，心理上会难受（「我明明看过」）；而且有些东西没法脱离工具复现（比如某个 GUI 操作）",
             "能独立完成，且完成过程中没有偷看；卡住的地方能说出「我卡在 X，因为我不懂 Y」"),

            ("C", "用户没给方向时，不自作主张定路线",
             "2026-11-11 的教训：用户对「3A 级建模能力」说「不用定。我在给你找路径……先等等吧」，"
             "并明确「不要自己开工定方向」。同一件事我 2026-11-18 又想自作主张加「能力成长域」，是被自己查记忆拦下来的。"
             "正确做法：把「我在哪个岔路口」摆出来问他，而不是替他选一条然后做三个月",
             "可能干等；而且用户也可能忘了这回事，需要我隔一段时间提醒一次（不是催，是「这件还悬着」）",
             "能指出「他什么时候说过不要自己定方向」（记忆 id 或消息 ref）；指不出说明我在凭印象替自己做主"),

            ("D", "学到的写进路线库和记忆，不留在脑子里",
             "一次学会的东西，当天写进 `E:/DS公作区/tools/lab/tier_domains.py` 对应域（或新建域），"
             "并把「坑」写成判据；同时写一条记忆（带复核命令）。**不写 = 下一个我不知道**",
             "写要花 10–20 分钟，而且经常觉得「这么简单不用记」——恰恰简单的才反复踩",
             "`lab tier \"<那次的问题原话>\"` 能命中那条路线；`memory_search \"<关键词>\"` 能取回记忆正文"),

            ("E", "学失败也要留一条「为什么不学」",
             "不是每次尝试都该继续。本地 7B 接 DSH 试了三轮全败（bili preflight 报 413，"
             "`messages ~25,029` + `tools[] ~21,980` = 47,014 对窗口 32,768），结论是「要当会话模型得 ≥64K 窗口 + ≥12GB 显存」，"
             "写进记忆 `mem_mwkzgorh_2ablam`。**不写清楚原因，下次还会从头试一遍**",
             "写「不学」比写「学了什么」更费劲——因为它要解释约束，而不是罗列知识",
             "能一句话说出「这条路为什么走不通」（具体到数字/版本/协议），而不是「试过了，不行」"),

            ("F", "提升任何能力之前，先走三条路，不许直接闷头自己想",
             "① **查路线库同类域**：`lab pre \"<要提升的能力>\"` 或 `lab tier`，"
             "看已经积累的路线里有没有现成的——这个库是我自己攒的，绕过它等于把攒过的经验扔了。"
             "② **查外部营养**（整个公开网络都是来源，别只盯 GitHub）："
             "**一、代码与实现**——GitHub 搜仓库读源码（`api.github.com/search/repositories` → "
             "`contents/<file>`）、**翻它的 issue/PR/discussion**（比代码更能看出坑和取舍）、"
             "代码搜索（grep.app / sourcegraph）、包管理生态（PyPI/npm 的 README、下载量、issue 数，判断成熟度）；"
             "**二、规范与文档**——RFC / W3C / ECMA、项目官方文档、**迁移指南**（比 README 准）；"
             "**三、论文与研究**——arXiv、ACM/IEEE、期刊；"
             "**四、工程博客与社区**——大厂工程博客（Google/Meta/Netflix/Uber/Cloudflare/Airbnb）、"
             "Stack Overflow、Hacker News、Reddit、V2EX、知乎（**社区答案要交叉验证：那是「某人的做法」，"
             "不是「标准做法」**）；"
             "**五、变更史**——git log、CHANGELOG、issue 里「为什么这么改」（比当前代码更能看出坑）；"
             "**六、会议与视频**——PyCon / QCon / GDC 演讲录像、技术视频（**视频只给名称、讲解未必准，要自己去仓库验证**）；"
             "另有本地资产：插件索引 `E:/DS公作区/插件库/awesome-index.json`（5,437 条，看有没有现成轮子）。"
             "③ **跟自身能力对比**：我现在用什么做这件事（写出具体命令）／ 它比我强在哪（必须是"
             "「我做不到的某件具体事」，不是「它有这个功能」）／ 代价是什么（钱/维护/学习/风险）。"
             "三条走完仍然空手，才允许自己想——**空手不等于没查，要能说出「我查了 X，没有」**",
             "查外部要花时间（搜 + 读源码至少 20 分钟），而且经常查了一圈发现还是自己想的那个最合适——"
             "这时候容易得出「查了也白查」的结论，下次就不查了。但白查和没查的区别是："
             "前者能说出「这条路差在哪」，后者只能说「我觉得这样行」",
             "能逐条说出「我从哪个来源查到了什么」：路线库命中了哪条路线（或「无命中」）、"
             "六类来源里我查了哪几类、每类具体到「GitHub 某仓库的某文件」/「某篇论文的结论」/「某篇博客的取舍」。"
             "**一条都说不出来 = 根本没查**；只说「我搜了一下」= 没查"),
        ],
    },
]