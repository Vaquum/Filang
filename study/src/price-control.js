import { h } from './ui/dom.js';
import { parseExpression, printExpr } from './lang.js';
import { CANDLE_ENUMS } from './candle-definitions.js';

const printed = (node, key, fallback) => {
  const arg = node?.args?.find(a => a.name === key || (key === 'point' && !a.name));
  return arg ? printExpr(arg.value) : fallback;
};
function options(labels, current) {
  return Object.entries(labels).map(([value, label]) =>
    h('option', {value, selected:value === current}, label));
}

export function priceControl(id, field) {
  const title = field.param.caption || field.name.replaceAll('_', ' ');
  const existing = parseExpression(field.value).ast;
  const names = {prior_low:'Prior range low', prior_high:'Prior range high'};
  if (field.param.type === 'Price') names.price = 'Candle endpoint';
  const source = h('select',{id},options(names,existing.name));
  const originalPoint = printed(existing, 'point', 'close');
  const points = {...CANDLE_ENUMS.PricePoint.labels};
  if (!Object.hasOwn(points, originalPoint)) points[originalPoint] = originalPoint;
  const point = h('select', {'aria-label': title + ' endpoint'}, options(points, originalPoint));
  const lag = h('input',{class:'arg-input', inputmode:'numeric','aria-label':title+' candles back',
    value:printed(existing,'bars_ago','0')});
  const duration = h('input',{class:'arg-input','aria-label':title+' lookback',
    value:printed(existing,'over','4h')});
  const candlestick = h('div',{class:'price-fields'},point,h('label',null,'Candles back',lag));
  const prior = h('label',null,'Lookback',duration);
  const input = h('input',{type:'hidden',value:field.value});
  function render() {
    candlestick.hidden = source.value !== 'price';
    prior.hidden = source.value === 'price';
  }
  function sync() {
    render();
    const bars = lag.value.trim();
    input.value = source.value === 'price'
      ? 'price(' + point.value + (bars === '0' ? '' : ', bars_ago: ' + bars) + ')'
      : source.value + '(over: ' + duration.value.trim() + ')';
  }
  render();
  for (const el of [source,point,lag,duration]) el.addEventListener(el.tagName === 'SELECT' ? 'change' : 'input',sync);
  return {
    input,
    focus: () => source.focus(),
    el:h('div',{class:'param-field'},h('label',{for:id},title),source,candlestick,prior,input),
  };
}
