#!/usr/bin/env python3
"""Extra numerical check because 6x10 misses a 1% criterion narrowly."""
import study,json
s=json.loads((study.OUT/'stage_selection.json').read_text())
c=next(x for x in s['candidates'] if x['stage']==[6,10]);p=c['rows'][-1]
r=study.execute('validation_rejected_6x10_halfstep',study.final([6,10],'tran',vc=p['vc'],amp=study.TARGET/16,stop=40,dt=1),dict(reason='Narrow 1% gain-deviation failure; numerical refinement only, no parameter change',stage=[6,10],gain=16,dt_ns=1))[0]
h=study.harmonics(r);hi=study.harmonics(r,node='v(vin)')
deviation=100*(h['fundamental_pp_V']/hi['fundamental_pp_V']/p['gain_1M']-1)
study.dump('rejected_halfstep_check.json',dict(baseline_gain_deviation_pct=p['gain_deviation_pct'],refined_gain_deviation_pct=deviation,refined_THD_pct=h['THD_pct'],still_fails=bool(abs(deviation)>1),target_output_Vpp=.350,maximum_step_ns=1))
print(deviation,h['THD_pct'])
