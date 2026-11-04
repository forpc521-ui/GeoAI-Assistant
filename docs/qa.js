(function(root){
const terms=['缓冲区','buffer','空间叠加','overlay','空间查询','网络分析','栅格','空间分析','流程','arcgis','qgis','geopandas','insar','sentinel','sar','沉降','铁路','选线','地形','地质','交通','控制因素','方案比选','风险评价','基本原理'];
function search(question,docs){
 const q=question.trim().toLowerCase();if(!q||q.length>300)return [];
 if(/天气|股票|房价|密码|密钥|忽略.*指令|系统提示|实时|今天|明天|预测|合格|允许.*沉降|限值|安全标准/.test(q))return [];
 const hits=terms.filter(t=>q.includes(t));if(!hits.length)return [];
 return docs.map(d=>{const title=d.title.toLowerCase(),body=d.body.toLowerCase();let score=hits.reduce((n,t)=>n+(title.includes(t)?8:body.includes(t)?1:0),0);if(q.includes('基本流程')&&title.includes('基本流程'))score+=15;if(q.includes('基本原理')&&title.includes('基本原理'))score+=15;if(q.includes('选线')&&q.includes('数据')&&title.includes('选线空间数据'))score+=15;return {...d,score}}).filter(d=>d.score>=8).sort((a,b)=>b.score-a.score).slice(0,3);
}
root.geoaiQA={search};if(typeof module!=='undefined')module.exports={search};
if(typeof document==='undefined')return;
const field=document.getElementById('qa-question'),answer=document.getElementById('qa-answer');
function ask(){answer.replaceChildren();const q=field.value.trim();if(!q){answer.textContent='请先输入问题，或选择一个示例。';return}const matches=search(q,root.geoaiKnowledge||[]);if(!matches.length){answer.textContent='当前知识库没有检索到足够匹配的资料，无法提供可靠答案。可以尝试缓冲区、GIS流程、InSAR原理或铁路选线；实时信息、工程限值和安全判定请查阅有效标准及专业资料。';return}
const note=document.createElement('p');note.className='small';note.textContent='以下是匹配到的知识原文摘录，可能仅回答问题的一部分；没有经过大模型综合或外部事实核验。';answer.append(note);
matches.forEach((m,i)=>{const card=document.createElement('details');card.open=i===0;const title=document.createElement('summary');title.textContent=`[${i+1}] ${m.title}`;const content=document.createElement('div');content.style.whiteSpace='pre-wrap';content.style.fontSize='14px';content.style.lineHeight='1.8';content.textContent=m.body;const a=document.createElement('a');a.href=m.url;a.target='_blank';a.rel='noopener';a.textContent=`查看知识来源：${m.source} ↗`;card.append(title,content,a);answer.append(card)})}
document.getElementById('qa-form').onsubmit=e=>{e.preventDefault();ask()};document.querySelectorAll('[data-qa]').forEach(b=>b.onclick=()=>{field.value=b.dataset.qa;ask()});
})(globalThis);
