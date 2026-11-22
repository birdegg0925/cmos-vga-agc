"""Create SVG charts directly from preserved summary data (standard library only)."""
from pathlib import Path
import json, html
ROOT=Path(__file__).resolve().parent; DATA=ROOT/'vga/results'; OUT=ROOT/'vga/figures'; OUT.mkdir(exist_ok=True)
def load(n):return json.loads((DATA/n).read_text())
COLORS=['#1c5795','#c25c25','#42734b']
def chart(name,title,xlabel,ylabel,series,xlim=None,ylim=None,limit=None,limit_label='Limit'):
    xs=[x for label,pts in series for x,y in pts];ys=[y for label,pts in series for x,y in pts]
    xa,xb=xlim or (min(xs),max(xs));ya,yb=ylim or (min(ys),max(ys))
    if xa==xb:xb+=1
    if ya==yb:yb+=1
    pad=(yb-ya)*.08
    if ylim is None:ya-=pad;yb+=pad
    X=lambda x:95+630*(x-xa)/(xb-xa);Y=lambda y:365-255*(y-ya)/(yb-ya)
    text=lambda x,y,s,size=15,anchor='middle':f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="Arial,sans-serif" font-size="{size}" fill="#17202a">{html.escape(str(s))}</text>'
    s=['<svg xmlns="http://www.w3.org/2000/svg" width="800" height="480" viewBox="0 0 800 480">','<rect width="800" height="480" fill="white"/>',text(400,32,title,21),text(400,57,'Replotted from recorded simulation summaries — no new simulation',12)]
    for k in range(6):
        v=ya+(yb-ya)*k/5;y=Y(v);s+=[f'<path d="M95 {y} H725" stroke="#dde2e8"/>',text(83,y+5,f'{v:.3g}',13,'end')]
        v=xa+(xb-xa)*k/5;x=X(v);s+=[text(x,389,f'{v:.3g}',13)]
    s += ['<path d="M95 110 V365 H725" stroke="#17202a" fill="none"/>',text(410,420,xlabel),f'<text transform="translate(25 235) rotate(-90)" text-anchor="middle" font-family="Arial,sans-serif" font-size="15">{html.escape(ylabel)}</text>']
    if limit is not None:s+=[f'<path d="M95 {Y(limit)} H725" stroke="#a12a32" stroke-dasharray="6 4"/>',text(720,Y(limit)-6,f'{limit_label} {limit:g}',12,'end')]
    for j,(label,points) in enumerate(series):
        color=COLORS[j%len(COLORS)];s+=[f'<polyline points="{" ".join(f"{X(x)},{Y(y)}" for x,y in points)}" fill="none" stroke="{color}" stroke-width="2.4"/>']
        for x,y in points:s+=[f'<circle cx="{X(x)}" cy="{Y(y)}" r="4" fill="{color}"/>']
        xx=100+j*245;s+=[f'<path d="M{xx} 84 h25" stroke="{color}" stroke-width="3"/>',text(xx+34,89,label,13,'start')]
    s+=['</svg>'];(OUT/(name+'.svg')).write_text('\n'.join(s)+'\n')
st=load('stage_selection.json')
chart('01_architecture_summary','Fixed-stage architecture comparison','Calibrated gain (V/V)','THD (%)', [(' × '.join(map(str,c['stage'])),[(r['target_gain'],r['THD_pct']) for r in c['rows']]) for c in st['candidates']],ylim=(0,1.3),limit=1)
cs=load('controller_selection.json')
chart('02_controller_summary','Controller speed comparison','Integral strength (1000/s)','Recovery within ±5% (µs)',[(label,[(r['ki_per_s']/1000,r['settling_us']) for r in cs['dynamic'] if (r['after_Vpp']<r['before_Vpp'])==down]) for label,down in [('36 → 259 mVpp',False),('259 → 36 mVpp',True)]],ylim=(0,90))
chart('03_ripple_summary','Controller ripple constraint','Integral strength (1000/s)','Weak-input control ripple (mVpp)',[('Recorded candidates',[(r['ki_per_s']/1000,r['weak_control_ripple_mV']) for r in cs['candidates']])],ylim=(0,.2),limit=.1)
cas=load('cascade_summary.json')
chart('04_cascade_summary','TIA–VGA steady amplitude regulation','Detector input current (µApp)','Steady output (mVpp)',[('Behavioural AGC',[(r['current_source_pp_A']*1e6,r['output_Vpp']*1000) for r in cas['agc']])],ylim=(345,355),limit=350,limit_label='Target')
print('Created four SVG plots from recorded summary tables.')
