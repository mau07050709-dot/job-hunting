from autojob.testing.simulation_4c import Simulator,SCENARIOS

def test_simulator_blocks_unknown_and_obstacles(tmp_path):
 s=Simulator(tmp_path);r=s.run('Obstáculos','Empresa ficticia','Customer Service')
 assert r['status']=='PENDIENTE'
 assert {'CAPTCHA','Personal video','Legal contract'} <= set(r['blockers'])
 assert not any(x['automatic'] for x in r['fields'] if x['kind'] in {'captcha','video','legal'})
 assert Simulator(tmp_path).history()[0]['id']==r['id']

def test_all_scenarios_no_real_applications(tmp_path):
 s=Simulator(tmp_path)
 for name in SCENARIOS:
  report=s.run(name,'Ejemplo','Developer');assert report['status']=='PENDIENTE'
 assert s.database.counts()=={}
 assert len(s.history())==4
