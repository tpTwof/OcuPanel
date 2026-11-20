const data = {"docs": ["杯盘比是眼底报告中的结构指标。", "计算面积等效杯盘比时，用视杯像素数除以整个视盘像素数，再开平方。", "将杯状区域面积除以完整盘状区域面积，再取平方根，就得到两者的等效直径比。", "视盘环与视杯面积之和构成整个视盘面积。", "分割掩膜记录各区域的像素标签。", "分割边界会影响面积测量。", "垂直直径比使用上下边缘的距离。", "报告中的分类概率描述模型输出。", "解读杯盘比时还需核查分割结果。", "分类概率不能直接表示严重程度。", "测量值会受到成像质量影响。", "解释分类结果时需核对类别。", "不同模型的分数需要分别解释。", "用户可以在历史报告页面下载 PDF。", "会话中可以选择已保存的报告。", "点击下载可导出报告文件。", "导出时核对报告所属账号。", "下载后的文件可离线查看。", "报告页面展示历史记录。", "登录前需要输入账号和密码。", "身份验证后才可访问个人数据。", "账号设置页可以测试模型连接。", "登录状态失效时需要再次认证。", "每个用户只能查看自己的会话。"], "qs": ["杯盘比的计算方法是什么？", "两个区域的大小比例怎么得出来？", "怎样解读报告中的分类概率？", "在哪里下载历史报告 PDF？"], "xy": [[-0.1431695818901062, 0.005933650769293308], [-0.17356514930725098, 0.07940564304590225], [-0.2109249234199524, 0.03021228313446045], [-0.13248002529144287, 0.07419924437999725], [-0.03499127924442291, 0.016366882249712944], [-0.111660435795784, 0.13616520166397095], [-0.11108139157295227, 0.1252135932445526], [-0.014186648651957512, -0.12157200276851654], [-0.09651372581720352, 0.027415992692112923], [-0.055351100862026215, 0.02785891480743885], [-0.049436844885349274, 0.16228392720222473], [-0.02774597331881523, 0.0383165217936039], [-0.0732480138540268, 0.030556580051779747], [0.1924411803483963, -0.11191631108522415], [0.13407282531261444, -0.034581370651721954], [0.14871931076049805, -0.14280381798744202], [0.16138963401317596, -0.04998806118965149], [0.13074110448360443, 0.050384677946567535], [0.14640025794506073, -0.11809756606817245], [0.19389881193637848, 0.11519394814968109], [0.1728830337524414, 0.13422636687755585], [0.13467085361480713, 0.095771424472332], [0.1644030660390854, 0.1322983354330063], [0.1396673321723938, 0.10780628025531769], [-0.2802716791629791, -0.12011678516864777], [-0.18978102505207062, -0.0900428295135498], [-0.15855342149734497, -0.2672269940376282], [0.14367398619651794, -0.3332638442516327]], "scores": [[0.9091033339500427, 0.9079581499099731, 0.9166086912155151, 0.8738251328468323, 0.8325791954994202, 0.8418643474578857, 0.851468563079834, 0.8422383069992065, 0.9174594879150391, 0.8387599587440491, 0.8355636596679688, 0.8272442817687988, 0.8476488590240479, 0.8223827481269836, 0.8185901641845703, 0.8240445852279663, 0.8143562078475952, 0.8258206248283386, 0.8215563893318176, 0.7959977388381958, 0.8101359605789185, 0.8187978863716125, 0.7974623441696167, 0.798324465751648], [0.8371238708496094, 0.8673105239868164, 0.8877695798873901, 0.8738447427749634, 0.8628685474395752, 0.8599785566329956, 0.8533875346183777, 0.8378943800926208, 0.848048210144043, 0.8413835167884827, 0.8292419910430908, 0.830419659614563, 0.8595290184020996, 0.8181976079940796, 0.8255525827407837, 0.8316851854324341, 0.8251861333847046, 0.8232308626174927, 0.8260543346405029, 0.8171916604042053, 0.8136557340621948, 0.8255351781845093, 0.8055974841117859, 0.8153616189956665], [0.8686439990997314, 0.8386069536209106, 0.85903000831604, 0.8371660709381104, 0.8483407497406006, 0.8331146836280823, 0.8250769376754761, 0.9331133365631104, 0.8664839863777161, 0.8925256133079529, 0.8300458788871765, 0.8812829852104187, 0.8814612030982971, 0.8306841254234314, 0.8493151664733887, 0.85024094581604, 0.8481576442718506, 0.8104903697967529, 0.852533221244812, 0.7837518453598022, 0.799436092376709, 0.8161349892616272, 0.8021813631057739, 0.8111496567726135], [0.8224698901176453, 0.8087009191513062, 0.8150696754455566, 0.8095786571502686, 0.8237702250480652, 0.8003992438316345, 0.7995796203613281, 0.8448356986045837, 0.8409674167633057, 0.8104261755943298, 0.7972301244735718, 0.8013497591018677, 0.8094373941421509, 0.9311684370040894, 0.855661928653717, 0.8990665674209595, 0.8713443279266357, 0.8550636768341064, 0.8970169425010681, 0.8288943767547607, 0.8277918696403503, 0.8393266201019287, 0.8272371292114258, 0.8091116547584534]]};
const $ = id => document.getElementById(id);
const {docs,qs,xy,scores} = data;
const code = i => String.fromCharCode(65+i);
const vocab = '杯盘比 计算 方法 两个 区域 大小 比例 怎么 得出 解读 报告 分类 概率 哪里 下载 历史 PDF 视杯 像素 面积 登录 会话'.split(' ').sort((a,b)=>b.length-a.length);
function tokens(text){
 const words=[];
 for(let i=0;i<text.length;){
  const token=vocab.find(w=>text.startsWith(w,i)) || text[i];
  if(/[\p{L}\p{N}]/u.test(token)) words.push(token);
  i+=token.length;
 }
 return words;
}
const corpus=docs.map(tokens), mean=corpus.reduce((a,b)=>a+b.length,0)/docs.length;
const stop=new Set('的是什么？在哪里怎样了得出来'.split(''));
let query=0, filter='', selected=0;
function bmScore(i,terms){
 const words=corpus[i];
 return terms.reduce((sum,t)=>{
  const tf=words.filter(w=>w===t).length,df=corpus.filter(d=>d.includes(t)).length;
  const idf=Math.log(1+(docs.length-df+.5)/(df+.5));
  return sum+idf*tf*2.2/(tf+1.2*(.25+.75*words.length/mean));
 },0);
}
const sortIds=values=>values.map((v,i)=>i).sort((a,b)=>values[b]-values[a]);
const options=qs.map((q,i)=>'<option value="'+i+'">'+q+'</option>').join('');
for(const id of ['query','q2']){
 $(id).innerHTML=options;
 $(id).onchange=e=>{query=Number(e.target.value);filter='';selected=sortIds(scores[query])[0];render()};
}
function showPoint(i){
 selected=i;
 $('point').textContent=code(i)+' · '+docs[i];
 $('cos').textContent='当前问题与片段 '+code(i)+' 的 384 维归一化向量逐项相乘后求和 = '+scores[query][i].toFixed(5)+'。';
}
function drawSpace(order){
 const host=$('plot');host.replaceChildren();
 const coords=xy.map(pair=>pair.slice());
 const bounds=[0,1].map(axis=>{const vals=coords.map(p=>p[axis]);return [Math.min(...vals),Math.max(...vals)]});
 const position=(el,p)=>{for(const [ax,prop] of ['left','bottom'].entries()){const [lo,hi]=bounds[ax];el.style[prop]=(6+88*(p[ax]-lo)/(hi-lo))+'%'}};
 docs.forEach((d,i)=>{const dot=document.createElement('button');dot.className='dot'+(order.slice(0,3).includes(i)?' top':'');dot.title=code(i)+' · '+d;dot.setAttribute('aria-label',dot.title);dot.onclick=dot.onfocus=()=>showPoint(i);position(dot,coords[i]);host.append(dot)});
 const q=document.createElement('span');q.className='queryDot';q.textContent='◆';position(q,coords[docs.length+query]);host.append(q);
 $('near').innerHTML=order.slice(0,3).map((i,j)=>'<button data-i="'+i+'">'+(j+1)+'　'+code(i)+' · '+docs[i]+'</button>').join('');
 $('near').querySelectorAll('button').forEach(b=>b.onclick=()=>showPoint(+b.dataset.i));showPoint(selected);
 $('projection').textContent='24 个圆点各代表一段资料。点击圆点可读原文；切换问题观察橙色菱形与蓝色邻居。坐标由本地 E5 实测向量经 PCA 投影得到，两个轴表示最大变化方向。圈出的邻居按完整向量选出，投影中的距离可能失真。';
}
function drawFusion(lex,semantic){
 const example=$('mode').selectedIndex===1,depth=+$('depth').value,k=+$('smooth').value;
 const lists=(example?[[0,1],[2,1]]:[lex,semantic]).map(l=>l.slice(0,depth));$('kval').textContent=k;
 const rows=[...new Set(lists.flat())].map(i=>{const ranks=lists.map(l=>l.indexOf(i)+1);return {i,ranks,total:ranks.reduce((s,r)=>s+(r?1/(k+r):0),0)}}).sort((a,b)=>b.total-a.total);
 const group=(name,items)=>'<div><b>'+name+'</b>'+items.map(x=>'<div class="row">'+x+'</div>').join('')+'</div>';
 $('ranks').innerHTML=lists.map((l,j)=>group(['BM25','E5'][j],l.map((i,r)=>(r+1)+'　片段 '+code(i)))).join('')+group('融合排名',rows.map((r,j)=>{const rank=rows.findIndex(x=>Math.abs(x.total-r.total)<1e-10)+1;return rank+'　片段 '+code(r.i)}));
 $('rrcalc').innerHTML=rows.map(r=>'<div class="row">'+code(r.i)+'　'+r.ranks.map(n=>n?'1/('+k+'+'+n+')':'0').join(' + ')+' = '+r.total.toFixed(5)+'</div>').join('');
}
function render(){
 $('query').value=$('q2').value=query;
 const terms=[...new Set(tokens(qs[query]).filter(w=>!stop.has(w)))];
 const all=docs.map((_,i)=>bmScore(i,terms)),lex=sortIds(all).filter(i=>all[i]>0),semantic=sortIds(scores[query]);
 $('terms').innerHTML=terms.map(t=>'<button class="'+(filter===t?'on':'')+'">'+t+'</button>').join(' ');
 $('terms').querySelectorAll('button').forEach(b=>b.onclick=()=>{filter=filter===b.textContent?'':b.textContent;render()});
 const active=filter?[filter]:terms, vals=docs.map((_,i)=>bmScore(i,active)),visible=sortIds(vals).filter(i=>vals[i]>0).slice(0,4);
 $('hits').innerHTML=visible.map(i=>'<div class="row">'+code(i)+'　'+tokens(docs[i]).map(t=>active.includes(t)?'<mark>'+t+'</mark>':t).join('')+'<span class="bar" style="width:'+100*vals[i]/vals[visible[0]]+'%"></span></div>').join('')||'这些词在当前资料中没有命中。';
 $('bmcalc').innerHTML=visible.map(i=>'<p>'+code(i)+'　'+active.filter(t=>corpus[i].includes(t)).map(t=>t+' '+bmScore(i,[t]).toFixed(2)).join(' + ')+' ≈ '+vals[i].toFixed(2)+'</p>').join('');
 drawSpace(semantic);drawFusion(lex,semantic);
}
$('sample').innerHTML=[0,1,2,8,13].map(i=>'<div class="row"><b>'+code(i)+'</b>　'+docs[i]+'</div>').join('');
for(const id of ['mode','depth','smooth'])$(id).oninput=render;
const glossary={TF:'词频 Term Frequency：一个词在当前片段中出现几次。',IDF:'逆文档频率 Inverse Document Frequency：用词在整库中的稀有程度衡量其区分力。',RRF:'倒数排名融合 Reciprocal Rank Fusion：把各条检索路线的名次换成贡献后相加。',BM25:'关键词相关性打分方法，综合词频、词的稀有度和文档长度。',E5:'文本向量模型，把问题和候选资料编码成可以比较的向量。',PCA:'主成分分析 Principal Component Analysis：沿数据变化最大的方向投影，在二维中近似观察高维结构。','余弦相似度':'Cosine similarity：比较两个向量的方向；归一化后可以用点积计算。'};
function dictionary(){const s=$('search').value.trim().toLowerCase();$('definitions').innerHTML=Object.entries(glossary).filter(pair=>pair.join(' ').toLowerCase().includes(s)).map(([k,v])=>'<p><b>'+k+'</b>　'+v+'</p>').join('')||'没有匹配的术语。'}
$('lookup').onclick=()=>{dictionary();$('dict').showModal();$('search').focus()};$('search').oninput=dictionary;$('close').onclick=()=>$('dict').close();
document.addEventListener('click',e=>{const tip=$('tip');if(!e.target.matches('.term')){tip.hidden=true;return}const r=e.target.getBoundingClientRect();tip.textContent=glossary[e.target.textContent];tip.hidden=false;tip.style.left=Math.min(r.left,innerWidth-tip.offsetWidth-8)+scrollX+'px';tip.style.top=r.bottom+scrollY+4+'px'});
const quiz=[['换到工程文档，查询精确设备编号时哪一路值得保留？','BM25 能利用编号的精确匹配，前提是分词保留编号。'],['点图中挨得最近的一定排名第一吗？','二维投影压缩了 384 维的信息，真正的排名要比较原始向量。'],['两路都漏掉正确资料，RRF 能找回吗？','不能。RRF 只能对已进入候选榜的资料重新排序。'],['第一名归一化分数是 1，代表引用正确吗？','它只表示本轮排名最高。证据能否支持具体陈述仍要核验。']];
$('qa').innerHTML=quiz.map(([q,a])=>'<div class="row"><b>'+q+'</b> <button aria-label="显示或隐藏答案" aria-pressed="false">N</button><div class="answer hide">'+a+'</div></div>').join('');
$('qa').querySelectorAll('button').forEach(b=>b.onclick=()=>{const hidden=b.nextElementSibling.classList.toggle('hide');b.textContent=hidden?'N':'Y';b.setAttribute('aria-pressed',String(!hidden))});
selected=sortIds(scores[0])[0];render();
