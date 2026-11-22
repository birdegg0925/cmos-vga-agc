"""Regenerate summary plots from recorded tables, without a simulator."""
from pathlib import Path
import csv, json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parent
DATA=ROOT/'vga/results'; OUT=ROOT/'vga/figures';OUT.mkdir(exist_ok=True)
def load(name):return json.loads((DATA/name).read_text())
def rows(name):
    with (DATA/name).open() as f:return list(csv.DictReader(f))
def save(name):
    plt.tight_layout();plt.savefig(OUT/(name+'.png'),dpi=160);plt.savefig(OUT/(name+'.svg'));plt.close()
plt.rcParams.update({'font.size':10,'axes.grid':True,'grid.alpha':.2})
fig,axes=plt.subplots(1,3,figsize=(12,3.7))
for candidate in load('stage_selection.json')['candidates']:
    data=candidate['rows'];x=[r['target_gain'] for r in data];label=' × '.join(map(str,candidate['stage']))
    for ax,key,label_y in zip(axes,['THD_pct','gain_deviation_pct','bandwidth_MHz'],['THD (%)','Gain deviation (%)','Bandwidth (MHz)']):
        ax.plot(x,[r[key] for r in data],'-o',label=label);ax.set(xlabel='Calibrated gain (V/V)',ylabel=label_y,xticks=x)
axes[0].axhline(1,color='r',ls='--',lw=1);axes[0].legend(title='Fixed-stage gains')
fig.suptitle('Recorded architecture sweep at nominal 350 mVpp output')
save('01_architecture_summary')
cs=load('controller_selection.json');fig,axes=plt.subplots(1,2,figsize=(9,3.7))
for down in [False,True]:
    data=[r for r in cs['dynamic'] if (r['after_Vpp']<r['before_Vpp'])==down]
    axes[0].plot([r['ki_per_s']/1000 for r in data],[r['settling_us'] for r in data],'-o',label='259 → 36 mVpp' if down else '36 → 259 mVpp')
axes[0].set(xlabel='Integral strength (1000/s)',ylabel='Recovery within ±5% (µs)');axes[0].legend()
c=cs['candidates'];axes[1].plot([r['ki_per_s']/1000 for r in c],[r['weak_control_ripple_mV'] for r in c],'-o')
axes[1].axhline(.1,color='r',ls='--',label='0.10 mVpp limit');axes[1].set(xlabel='Integral strength (1000/s)',ylabel='Weak-input control ripple (mVpp)');axes[1].legend()
save('02_controller_summary')
cas=load('cascade_summary.json');fig,axes=plt.subplots(1,2,figsize=(9,3.7))
axes[0].plot([r['current_source_pp_A']*1e6 for r in cas['agc']],[r['output_Vpp']*1000 for r in cas['agc']],'-o');axes[0].axhline(350,color='k',ls='--');axes[0].set(xlabel='Detector current (µApp)',ylabel='Steady output (mVpp)',ylim=(345,355))
axes[1].plot([r['gain_setting'] for r in cas['ac']],[r['bandwidth_MHz'] for r in cas['ac']],'-o');axes[1].set(xlabel='Fixed VGA gain (V/V)',ylabel='Cascade bandwidth (MHz)',xticks=[1,4,16],ylim=(7.1,7.2))
save('03_cascade_summary')
temps=rows('verified_temperature.csv');fig,axes=plt.subplots(1,2,figsize=(9,3.7));x=[float(r['temperature_C']) for r in temps]
axes[0].plot(x,[float(r['amplitude_error_pct']) for r in temps],'o-');axes[0].set(xlabel='Model temperature (°C)',ylabel='Amplitude error (%)',ylim=(-5,5))
axes[1].plot(x,[float(r['THD_pct']) for r in temps],'o-');axes[1].axhline(1,color='r',ls='--',label='1% limit');axes[1].set(xlabel='Model temperature (°C)',ylabel='THD (%)');axes[1].legend()
fig.suptitle('Recorded temperature checks at 100 mVpp input; no retuning')
save('04_temperature_limit')
print('Regenerated four figures from preserved summary tables; no fresh SPICE simulation.')
