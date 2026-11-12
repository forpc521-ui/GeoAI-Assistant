/* Historical evidence only. No model request, secret, or user upload. */
(() => {
  const data = window.geoaiReplay;
  const el = id => document.getElementById(id);
  const textNode = (tag, text) => {
    const node = document.createElement(tag);
    node.textContent = text;
    return node;
  };
  const showParse = () => {
    const id = el('parse-replay').value;
    const rows = data.parsing.filter(row => row.id === id);
    const output = el('parse-evidence');
    output.replaceChildren();
    for (const row of rows) {
      const panel = document.createElement('div');
      panel.className = 'evidence-panel';
      panel.append(textNode('h3', row.mode));
      panel.append(textNode('p', row.query));
      panel.append(textNode('p', row.actual
        ? `保存的解析结果：${row.actual[0]} · ${row.actual[1]} 米`
        : `保存的处理信息：${row.message || '无解析结果'}`));
      panel.append(textNode('p', `该条开发用例判定：${row.correct ? '符合预期' : '不符合预期'}。不代表通用成功率。`));
      output.append(panel);
    }
  };
  const showAnswer = () => {
    const row = data.answers.find(row => row.id === el('answer-replay').value);
    const output = el('answer-evidence');
    output.replaceChildren(textNode('h3', row.question), textNode('p', row.answer || row.error || '本条没有成功回答'));
    if (row.id === 'R14') output.append(textNode('p', '已发现的问题：回答扩展到“滑坡、崩塌”，检索原文未明确提供，记为无依据扩展；不能由此判定常识为假。'));
    const details = document.createElement('details');
    details.append(textNode('summary', '展开这次返回的检索来源与原文'));
    for (const hit of row.hits || []) {
      details.append(textNode('h4', hit.source), textNode('p', hit.content));
    }
    output.append(details);
  };
  el('parse-replay').addEventListener('change', showParse);
  el('answer-replay').addEventListener('change', showAnswer);
  showParse();
  showAnswer();
})();
