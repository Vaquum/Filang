const enumDef = (name, title, labels) => ({ name, title, values: Object.keys(labels), labels });
export const CANDLE_ENUMS = {
  PricePoint: enumDef('PricePoint', 'candle price', {
    open: 'Open', high: 'High', low: 'Low', close: 'Close', body_low: 'Body low', body_high: 'Body high',
  }),
  CandlePart: enumDef('CandlePart', 'candle part', {
    body: 'Body', lower_wick: 'Lower wick', upper_wick: 'Upper wick',
  }),
  PriceRelation: enumDef('PriceRelation', 'price comparison', {
    above: 'Above', at_or_above: 'At or above', below: 'Below', at_or_below: 'At or below',
    equal: 'Equal to', unequal: 'Different from',
  }),
};
const over = { name: 'over', type: 'Duration', default: '4h',
  domain: { barMultiple: true, minMs: 900_000, maxMs: 7 * 86_400_000 },
  doc: 'Trailing window ending before the candle being tested.' };
const bars = (name, defaultValue, doc) => ({
  name, type: 'Number', default: String(defaultValue), domain: { wholeMax: 64 }, doc,
});
const limit = (name, defaultValue, doc, domain = {}) => ({
  name, type: 'Ratio', default: defaultValue, domain, doc,
});
const point = { name: 'point', type: 'Cat:PricePoint', default: 'close', doc: 'Price to read from the selected candle.' };
const level = (name, type, doc) => ({ name, type, required: true, doc });
const setup = (d) => ({
  status:'implemented', version: 1, requires: ['bars.ohlc'], formula:[d.summary],
  anchor:'The deciding candle close.', availability:'Completed candles through the deciding close.',
  ...d,
});
const defs = [
  setup({
    name:'price', kind:'reference', result:'Price', title:'Candle price', positional:'point',
    summary:'Read an endpoint of a completed candle by its lag on the bar grid.',
    params:[point, bars('bars_ago',0,'Zero is the current candle. One is the previous candle.')],
    missing:'The requested candle is absent.', template:a=>a.bars_ago === '0' ? a.point : a.point + ' ' + a.bars_ago + ' bars ago',
    example:'price(low)',
  }),
  ...['low','high'].map(side=>setup({
    name:'prior_'+side, kind:'reference', result:'Level', title:'Prior range '+side,
    summary:'The '+side+'est '+side+' of the preceding complete window. The candle being tested is excluded.',
    params:[over], missing:'Any missing candle in the lookback leaves the level unknown.',
    template:a=>'prior '+a.over+' '+side, example:'prior_'+side+'(over: 4h)',
  })),
  setup({
    name:'breach_reclaim', kind:'event', result:'Event', title:'Prior range reclaim', positional:'reference',
    params:[level('reference','Level','Choose the prior range low or high. This level is frozen on the breach candle.'),
      bars('within_min',0,'Earliest reclaim offset in candles. Use zero to include the breach candle.'),
      bars('within_max',0,'Last reclaim offset in candles. Zero means the breach candle only.')],
    orderedBounds:['within_min','within_max'],
    summary:'Pierce a prior range boundary and record the first close strictly back inside, using the level at the breach.',
    missing:'A missing candle can make the first reclaim unknown. A known matching breach can still establish a reclaim.',
    template:a=>a.within_max === '0' ? 'same-candle reclaim of '+a.reference
      : 'reclaim '+a.reference+' in '+a.within_min+'–'+a.within_max+' candles',
    example:'breach_reclaim(prior_low(over: 4h))',
  }),
  setup({
    name:'candle_relation', kind:'event', result:'Event', title:'Compare candle prices', positional:'left',
    params:[level('left','Price','First candle endpoint or prior range level.'),
      {name:'is',type:'Cat:PriceRelation',default:'above',doc:'Exact comparison.'},
      level('right','Price','Second candle endpoint or prior range level.')],
    summary:'Test an exact price relationship between two chosen endpoints or prior range levels.',
    missing:'An unavailable operand makes the relationship unknown.',
    template:a=>a.left+' '+a.is.toLowerCase()+' '+a.right,
    example:'candle_relation(price(close), is: above, right: price(high, bars_ago: 1))',
  }),
  setup({
    name:'candle_share', kind:'condition', result:'Condition', title:'Wick or body share', positional:'part',
    params:[{name:'part',type:'Cat:CandlePart',default:'lower_wick',doc:'Part measured as a share of the entire candle.'},
      limit('min','50%','Minimum share, inclusive.',{ratioMax:'1'}),
      limit('max','100%','Maximum share, inclusive.',{ratioMax:'1'}),
      bars('bars_ago',0,'Zero is the current candle. One is the previous candle.')],
    orderedBounds:['min','max'],
    summary:'The selected wick or body, divided by the high–low range, is between the chosen bounds.',
    missing:'An absent candle or zero range makes the ratio unknown.',
    template:a=>a.part+' '+(a.bars_ago === '0' ? '' : a.bars_ago+' bars ago ')+'between '+a.min+' and '+a.max+' of the range',
    example:'candle_share(lower_wick, min: 50%)',
  }),
  setup({
    name:'range_multiple', kind:'condition', result:'Condition', title:'Range versus recent median',
    params:[over,limit('min','1.5','Minimum multiple of recent median range, inclusive.'),
      limit('max',undefined,'Maximum multiple of recent median range, inclusive.')],
    orderedBounds:['min','max'],
    summary:'The current high–low range is measured against the median of the preceding completed candles.',
    missing:'A missing candle or zero reference median makes the comparison unknown.',
    template:a=>'range '+(a.max ? a.min+' to '+a.max : 'at least '+a.min)+' × prior '+a.over+' median',
    example:'range_multiple(over: 4h, min: 1.5)',
  }),
  setup({
    name:'near_level', kind:'condition', result:'Condition', title:'Price near a level', positional:'reference',
    params:[level('reference','Price','The base price for measuring distance.'),level('point','Price','The price to compare.'),
      limit('within','0.25%','Largest absolute distance, as a fraction of the reference.',{ratioMax:'1'})],
    summary:'The absolute difference between two prices is at most the given percentage of the reference.',
    missing:'An unavailable operand makes the measured distance unknown.',
    template:a=>a.point+' within '+a.within+' of '+a.reference,
    example:'near_level(prior_high(over: 4h), point: price(close), within: 0.25%)',
  }),
];
export const CANDLE_DEFINITIONS = defs;
