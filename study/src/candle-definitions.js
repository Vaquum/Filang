const enumDef = (name, title, labels) => ({ name, title, values: Object.keys(labels), labels });

// The dimensions a g1 code can switch on, read here one candle at a time (docs/G1_DIMENSIONS.md). Keys and labels
// are Cube's. A signed dimension has zero as its reference point: below it is net selling, above it net buying.
export const DIMENSION_INFO = Object.freeze({
  volume: { label: 'Volume', what: 'USDT traded', signed: false },
  trades: { label: 'Trades', what: 'number of trades', signed: false },
  delta: { label: 'Delta', what: 'taker-buy USDT minus taker-sell USDT', signed: true },
  size: { label: 'Trade size', what: 'USDT traded per trade', signed: false },
  imbalance: { label: 'Net taker imbalance', what: 'delta as a share of the USDT traded, from −1 to +1', signed: true },
});
const NEEDS_COUNTERS = "the bars' USDT traded, taker-buy USDT and trade count, which this recording does not provide";

/** The axis an operand lies on: price, a dimension, or the literal zero. Values on different axes are never compared. */
export function axisOf(p) {
  if (p.type === 'Zero') return 'zero';
  if (p.type === 'Reading') return p.def.dimension;
  return p.type === 'Level' && p.args.of ? p.args.of.value : 'price';
}
const priceOnly = (name, ...params) => (a) => {
  const off = params.map((k) => a[k]).find((p) => p && axisOf(p) !== 'price');
  return off ? { kind: 'type', message: `${name} works on prices; ${off.text} is a reading of ${axisOf(off)}` } : null;
};

export const CANDLE_ENUMS = {
  Dimension: enumDef('Dimension', 'dimension', Object.fromEntries(Object.entries(DIMENSION_INFO).map(([k, v]) => [k, v.label]))),
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
  caption: {within_min:'Earliest reclaim (candles)', within_max:'Latest reclaim (candles)', bars_ago:'Candles back'}[name],
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
    summary:'The '+side+'est '+side+' of the preceding complete window. The candle being tested is excluded. With of:, the '+side+'est value of that dimension over the same window.',
    params:[over, {name:'of', type:'Cat:Dimension', doc:'Take the level from this dimension of the candles instead of from their prices.'}],
    missing:'Any missing candle in the lookback, or one without the value, leaves the level unknown.',
    validate:(a, env)=>a.of && !env.recording.caps.has('bars.counters')
      ? {kind:'capability', message:'prior_'+side+' of '+a.of.value+' needs '+NEEDS_COUNTERS} : null,
    template:a=>'prior '+a.over+' '+(a.of ? a.of.toLowerCase()+' ' : '')+side, example:'prior_'+side+'(over: 4h)',
  })),
  ...Object.entries(DIMENSION_INFO).map(([name, info])=>setup({
    name, kind:'reference', result:'Reading', dimension:name, title:info.label+' of a candle', requires:['bars.counters'],
    summary:'Read a completed candle\'s '+info.what+', by its lag on the bar grid.',
    params:[bars('bars_ago',0,'Zero is the current candle. One is the previous candle.')],
    missing:'The requested candle is absent, or has no such value.',
    template:a=>a.bars_ago === '0' ? name : name+' '+a.bars_ago+' bars ago', example:name+'()',
  })),
  setup({
    name:'breach_reclaim', kind:'event', result:'Event', title:'Prior range reclaim', positional:'reference',
    params:[level('reference','Level','Choose the prior range low or high. This level is frozen on the breach candle.'),
      bars('within_min',0,'Earliest reclaim offset in candles. Use zero to include the breach candle.'),
      bars('within_max',0,'Last reclaim offset in candles. Zero means the breach candle only.')],
    orderedBounds:['within_min','within_max'],
    summary:'Pierce a prior range boundary and record the first close strictly back inside, using the level at the breach.',
    missing:'A missing candle can make the first reclaim unknown. A known matching breach can still establish a reclaim.',
    validate:priceOnly('breach_reclaim','reference'),
    template:a=>a.within_max === '0' ? 'same-candle reclaim of '+a.reference
      : 'reclaim '+a.reference+' in '+a.within_min+'–'+a.within_max+' candles',
    example:'breach_reclaim(prior_low(over: 4h))',
  }),
  setup({
    name:'candle_relation', kind:'event', result:'Event', title:'Compare candle prices', positional:'left', readings:true,
    params:[level('left','Price','First candle endpoint or prior range level, or a reading of a dimension.'),
      {name:'is',type:'Cat:PriceRelation',default:'above',doc:'Exact comparison.'},
      level('right','Price','Second candle endpoint or prior range level, or a reading of the same dimension. 0 for delta and imbalance.')],
    summary:'Test an exact relationship between two chosen endpoints or prior range levels, or between two readings of one dimension. Delta and imbalance can also be compared with 0.',
    missing:'An unavailable operand makes the relationship unknown.',
    validate:(a)=>{
      const l = axisOf(a.left), r = axisOf(a.right);
      if (l === r && l !== 'zero') return null;
      const other = l === 'zero' ? r : r === 'zero' ? l : null;
      if (other && DIMENSION_INFO[other]?.signed) return null;
      return {kind:'type', message: other
        ? '0 is the reference point of delta and imbalance only; '+(other === 'zero' ? 'it cannot be compared with itself' : other+' has none')
        : 'candle_relation compares two values on one axis; '+a.left.text+' is '+(l === 'price' ? 'a price' : l)+' and '+a.right.text+' is '+(r === 'price' ? 'a price' : r)};
    },
    template:a=>a.left+' '+a.is.toLowerCase()+' '+a.right,
    example:'candle_relation(price(close), is: above, right: price(high, bars_ago: 1))',
  }),
  setup({
    name:'candle_window',kind:'event',result:'Event', title:'Consecutive candle pattern', positional:'event',
    params:[level('event','Event','An event or combined candle relationships, tested at the final close.'),
      {...bars('bars',2,'Consecutive candles required through this close.'), domain:{wholeMin:1,wholeMax:64}}],
    summary:'Require a fully recorded consecutive window ending at the event close.',
    missing:'An incomplete window makes the event unknown.',
    template:a=>a.event+' in '+a.bars+' consecutive candles',
    example:'candle_window(inside_bar, bars: 2)',
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
    validate:priceOnly('near_level','reference','point'),
    missing:'An unavailable operand makes the measured distance unknown.',
    template:a=>a.point+' within '+a.within+' of '+a.reference,
    example:'near_level(prior_high(over: 4h), point: price(close), within: 0.25%)',
  }),
  setup({
    name:'dimension_multiple', kind:'condition', result:'Condition', title:'Dimension versus recent median', positional:'dimension',
    requires:['bars.counters'],
    params:[{name:'dimension',type:'Cat:Dimension',default:'volume',doc:'Volume, trades or size.'},
      over,limit('min','1.5','Minimum multiple of the recent median, inclusive.'),
      limit('max',undefined,'Maximum multiple of the recent median, inclusive.')],
    orderedBounds:['min','max'],
    summary:'The current candle\'s value is measured against the median of the preceding completed candles.',
    formula:['m = the two middle values of the preceding window, added (the same value twice for an odd count).',
      'The condition holds when 2 × value ≥ min × m and, with max, 2 × value ≤ max × m, each operation in 64-bit floats as written.'],
    missing:'A missing candle, a candle without the value, or a zero median makes the comparison unknown.',
    validate:(a)=>DIMENSION_INFO[a.dimension.value].signed
      ? {kind:'domain', message:'a multiple of the median needs a dimension that cannot be negative: volume, trades or size'} : null,
    template:a=>a.dimension.toLowerCase()+' '+(a.max ? a.min+' to '+a.max : 'at least '+a.min)+' × prior '+a.over+' median',
    example:'dimension_multiple(volume, over: 4h, min: 1.5)',
  }),
];
export const CANDLE_DEFINITIONS = defs;
