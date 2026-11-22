#!/usr/bin/env python3
"""Bounded follow-up verification; no redesign or new parameter draw."""
import study,json
from pathlib import Path
P=study.P;OUT=study.OUT
amendment=dict(purpose='Bounded verification of high-gain linearity and temperature sensitivity after frozen design selection, not a selection change.',
    tests=dict(gain16_input_mVpp=list(range(20,27)),AGC_temperatures_C=[0,70],AGC_input_mVpp=100,AGC_target_mVpp=350),
    fixed='Use selected stage, nominal calibrated controls, selected Ki. Do not retune at temperature.',
    criteria=dict(linearity_THD_pct_max=1,linearity_absolute_gain_deviation_pct_max=1,AGC_amplitude_error_pct_max=5),
    ordering='Written before these additional verification runs. Results do not trigger parameter redraw or selection override.')
dest=study.ROOT/'validation_extension_protocol.json'
if not dest.exists():dest.write_text(json.dumps(amendment,indent=2))
else:assert json.loads(dest.read_text())==amendment
s=json.loads((OUT/'stage_selection.json').read_text());stage=s['selected_stage'];c=next(x for x in s['candidates'] if x['stage']==stage);tag=c['tag'];points=json.loads((OUT/(tag+'_points.json')).read_text());high=points[-1]
ctrl=json.loads((OUT/'controller_selection.json').read_text())['selected'];ki=ctrl['ki_per_s']
cases=[dict(vc=high['vc'],amp=a*1e-3) for a in range(20,27)]
rr=study.execute('verify_highgain_input_grid',study.cases(stage,'tran',cases,stop=40,dt=1),amendment['tests'])
rows=[]
for a,r in zip(range(20,27),rr):
    h=study.harmonics(r);hi=study.harmonics(r,node='v(vin)');dev=100*(h['fundamental_pp_V']/hi['fundamental_pp_V']/c['rows'][-1]['gain_1M']-1)
    rows.append(dict(input_mVpp=a,THD_pct=h['THD_pct'],gain_deviation_pct=dev,output_mVpp=h['vpp_V']*1e3,passes=bool(h['THD_pct']<=1 and abs(dev)<=1)))
study.table('verified_highgain_linearity.csv',rows)
temps=[]
for temp in [0,70]:
    name=f'verify_agc_temperature_{temp}C';deck=study.agc(stage,points,amp=.1,ki=ki).replace('.temp {tdeg}',f'.temp {temp}')
    r=study.execute(name,deck,dict(temperature_C=temp,input_Vpp=.1,target_Vpp=.35,ki_per_s=ki,controls='nominal unchanged'))[0]
    m=study.cyc_metrics(r,name,.1,ki);m['temperature_C']=temp;m['amplitude_passes_5pct']=abs(m['amplitude_error_pct'])<=5;m['THD_passes_1pct']=m['THD_pct']<=1;temps.append(m)
study.table('verified_temperature.csv',temps)
study.dump('existing_claims_verification.json',dict(linearity=rows,highest_tested_passing_input_mVpp=max((r['input_mVpp'] for r in rows if r['passes']),default=None),lowest_tested_failing_input_mVpp=min((r['input_mVpp'] for r in rows if not r['passes']),default=None),temperatures=temps,scope='Tested grid, not continuous limit; temperature tests do not prove process corners or manufacture qualification.'))
print(json.dumps(dict(linearity=rows,temperature=temps),indent=2))
