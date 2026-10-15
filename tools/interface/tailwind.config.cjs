// Compile at build time. No runtime Tailwind compiler or DOM style observer.
const palette = (name) => Object.fromEntries([50,100,200,300,400,500,600,700,800,900].map(n => [n,`var(--${name}-${n})`]));
module.exports = {
 content: ['./horilla_theme/templates/**/*.html','./templates/**/*.html','./*/templates/**/*.html','./horilla_theme/static/**/*.js','./static/index/*.js','./*/cbv/*.py'],
 darkMode: 'class',
 safelist: [
  {pattern: /^(bg|text|border)-(primary|brand|secondary|dark|info|success|warning|danger)-(50|100|200|300|400|500|600|700|800|900|light|dark)$/,variants:['hover','focus','group-hover','dark']},
  'bg-success','bg-warning','bg-danger','text-success','text-warning','text-danger','hidden','block','flex','grid', 'opacity-0','opacity-100','scale-95','scale-100',
 ],
 theme: {extend: {
  colors: {primary:palette('primary'),brand:palette('primary'),secondary:palette('secondary'),dark:palette('dark'),info:palette('info'),color:{600:'#374151'},success:{light:'#bbf7d0',DEFAULT:'#16804a',dark:'#166534'},warning:{light:'#fef3c7',DEFAULT:'#a16207',dark:'#854d0e'},danger:{light:'#fee2e2',DEFAULT:'#b91c1c',dark:'#991b1b'}},
  boxShadow:{card:'0 2px 8px rgb(16 18 24 / 4%)'},spacing:{18:'4.5rem',84:'21rem'},borderRadius:{'4xl':'2rem','5xl':'2.5rem'},fontSize:{xxs:'0.625rem'},height:{'screen-50':'50vh','screen-75':'75vh'}
 }}
};
