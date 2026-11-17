"""Self-authored latent event scenarios. This module is never a runtime dependency.

Truth is created when an event is drawn, before source formatting. Category
choices belong to latent catalog items, not rules copied from production.
"""
import csv
from decimal import Decimal
import json
from pathlib import Path
import random

# Evaluation-only fictional catalog. Translations/paraphrases intentionally
# stretch a lexical model; no aliases below are sent to the production classifier.
CATALOG = [
(('Food service','Kitchen equipment','Cooking','Ovens'),'commercial convection oven','fan assisted baking chamber','four professionnel'),
(('Food service','Kitchen equipment','Cooling','Refrigerators'),'kitchen refrigerator','cold cabinet for ingredients','refrigerador de cocina'),
(('Food service','Kitchen equipment','Washing','Dishwashers'),'commercial dishwasher','automatic plate washing machine','lavavajillas comercial'),
(('Food service','Table supplies','Cutlery',''),'stainless cutlery set','dining forks and knives','cubiertos de mesa'),
(('Food service','Table supplies','Glassware',''),'drinking glassware','water tumblers for restaurant','copas de cristal'),
(('Housekeeping','Cleaning supplies','Chemicals','Detergents'),'laundry detergent','fabric washing concentrate','detergente de lavanderia'),
(('Housekeeping','Cleaning supplies','Chemicals','Disinfectants'),'surface disinfectant','antibacterial sanitising liquid','desinfectante'),
(('Housekeeping','Cleaning equipment','Vacuum cleaners',''),'vacuum cleaner','powered dust suction machine','aspiradora'),
(('Housekeeping','Room textiles','Bedding','Sheets'),'cotton bedding sheets','white linen for guest beds','sabanas de algodon'),
(('Housekeeping','Room textiles','Bathroom','Towels'),'bathroom towels','absorbent guest bath linen','toallas de bano'),
(('Building maintenance','Electrical','Lighting','LED lamps'),'LED lighting lamps','low energy replacement luminaires','lamparas LED'),
(('Building maintenance','Electrical','Power distribution','Switches'),'electrical power switch','wall mounted isolator','interruptor electrico'),
(('Building maintenance','Plumbing','Water systems','Valves'),'water plumbing valve 25mm','quarter turn liquid flow control 25mm','valvula de agua 25mm'),
(('Building maintenance','Plumbing','Water systems','Pumps'),'water circulation pump','motor driven liquid transfer unit','bomba de agua'),
(('Building maintenance','Air conditioning','Cooling','Compressors'),'air conditioning compressor','refrigerant pressure unit','compresor de aire acondicionado'),
(('Guest services','Room amenities','Personal care','Soap'),'guest bathroom soap','individual hand washing bar','jabon para huespedes'),
(('Guest services','Room amenities','Personal care','Shampoo'),'guest shampoo','hair cleansing bottle','champu'),
(('Guest services','Transport','Passenger vehicles',''),'passenger shuttle vehicle','airport guest transfer minibus','vehiculo de pasajeros'),
(('Guest services','Activities','Recreation','Equipment'),'recreation sports equipment','poolside games accessories','equipamiento deportivo'),
(('Information technology','Computing','Hardware','Laptops'),'laptop computer','portable staff workstation','ordenador portatil'),
(('Information technology','Computing','Hardware','Monitors'),'computer monitor display','desktop viewing screen','monitor de ordenador'),
(('Information technology','Networking','Hardware','Switches'),'network ethernet switch','managed packet forwarding appliance','conmutador de red'),
(('Information technology','Software','Business applications',''),'business software licence','annual office application subscription','licencia de software'),
(('Information technology','Support','Professional services',''),'computer support service','workstation troubleshooting engineer','soporte informatico'),
]
FIELDS=['line_id','amount','description','vendor','supplier','material','po','po_item','invoice','invoice_line','receipt','qty','currency','rate','invoice_date','status','vat','account_text','source_system','supplier_type']


def write_csv(path, rows, fields):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf-8') as out:
        writer=csv.DictWriter(out,fieldnames=fields)
        writer.writeheader();writer.writerows(rows)


def source(name,file,prefix='',priority=0,gross=False):
    return {'name':name,'file':file,'prefix':prefix,'priority':priority,
            'columns':{'record_id':'line_id','amount':'amount','description':'description',
                       'supplier_id':'vendor','supplier_name':'supplier','item_id':'material',
                       'po':'po','po_item':'po_item','invoice':'invoice','invoice_line':'invoice_line',
                       'receipt':'receipt','quantity':'qty','currency':'currency','fx_rate':'rate',
                       'date':'invoice_date','status':'status','vat_rate':'vat','context':['account_text']},
            'currency':'USD','amount_semantics':'gross' if gross else 'net','default_vat':'15%',
            'decimal_separator':'.','thousands_separator':',','date_formats':['%Y-%m-%d','%d/%m/%Y'],
            'supplier_namespace':'shared','item_namespace':'shared',
            'status':{'missing':'approved','approved':['Approved','Paid'],'cancelled':['Cancelled']},
            'reexports':gross}


def base_config(sources):
    return {'version':1,'reporting_currency':'USD','taxonomy':{'file':'taxonomy.csv','columns':['l1','l2','l3','l4']},
            'sources':sources,'classifier':{'mode':'lexical'},
            'non_procurement':[{'field':'supplier_type','values':['intercompany','tax-authority']}],
            'financial':{'missing_amount':'error'}}


def generate_case(directory,kind='C',seed=1,size=None):
    directory=Path(directory); raw=directory/'raw'; raw.mkdir(parents=True,exist_ok=True)
    rng=random.Random(seed)
    size=size if size is not None else {'A':400,'B':600,'C':1500}[kind]
    paths=[tuple(x[0]) for x in CATALOG]
    shuffled=paths.copy();rng.shuffle(shuffled)
    write_csv(raw/'taxonomy.csv',[dict(zip(['l1','l2','l3','l4'],p)) for p in shuffled],['l1','l2','l3','l4'])
    ledger=[]; rendered={}; events=[]
    sources=[source('erp','erp.csv','ERP:',0),source('tool','tool.csv','TOOL:',1,True)] if kind=='A' else [source('ledger','invoices.csv')]
    config=base_config(sources)
    if kind=='B':
        config['sources'][0]['namespace_column']='source_system'
        config['fx']={'file':'fx.csv','currency_column':'currency','month_column':'month','rate_column':'units_per_usd','direction':'units_per_reporting'}
        write_csv(raw/'fx.csv',[{'currency':'EUR','month':'2024-02','units_per_usd':'0.8'},
                                {'currency':'ZAR','month':'2024-02','units_per_usd':'20'}],['currency','month','units_per_usd'])
    for s in sources: rendered[s['name']]=[]
    for i in range(size):
        topic=rng.randrange(len(CATALOG)); path,direct,paraphrase,translated=CATALOG[topic]
        roll=rng.random()
        description=direct if roll<.64 else paraphrase if roll<.82 else translated if roll<.94 else ' '
        context=' '.join(path[:2]) if roll>=.94 and i%2 else ''
        informative=bool(description.strip() or context)
        status=rng.choices(['Approved','Paid','Cancelled','On Hold'],[.70,.20,.05,.05])[0]
        nonproc=rng.random()<.045
        reason='CANCELLED' if status=='Cancelled' else 'NOT_APPROVED' if status=='On Hold' else 'NON_PROCUREMENT' if nonproc else ''
        net=Decimal(rng.randrange(1,1800)*20)
        if i%31==0:net=-net
        if i%79==0:net=Decimal(0)
        supplier=f'vendor-{rng.randrange(24):02}'
        item=f'catalog-{topic:02}'
        namespace=f'ERP-{i%4}' if kind=='B' else 'shared'
        event={'event_id':f'event-{seed}-{i}','supplier':f'{namespace}:{supplier}',
               'item':f'{namespace}:{item}','path':list(path),'net':str(net),'reason':reason,
               'informative':informative,'status':status,'description':description,'context':context}
        events.append(event)
        base={k:'' for k in FIELDS}
        base.update(line_id=f'R{i:07}',amount=str(net),description=description,vendor=supplier,
                    supplier=f'Fictional Supply {supplier[-2:]} Ltd' if i%2 else f'Fictional Supply {supplier[-2:]}',
                    material=item,po=f'PO-{seed}-{i}',po_item='10',invoice=f'INV-{seed}-{i}',invoice_line='1',
                    receipt=f'RC-{seed}-{i}',qty='1',currency='USD',invoice_date='2024-02-29',status=status,
                    account_text=context,source_system=namespace,supplier_type='tax-authority' if nonproc else 'trade')
        def add(s,row,duplicate=False):
            rendered[s['name']].append(row)
            why=reason or ('DUPLICATE' if duplicate else '')
            ledger.append({'record_id':s['prefix']+row['line_id'],'include':not bool(why),'reason':why,
                           'spend':'0' if why else str(net),'path':list(path),
                           'supplier':event['supplier'],'item':event['item'],'informative':informative,
                           'event_id':event['event_id']})
        if kind=='A':
            erp,tool=sources
            in_erp=rng.random()<.80
            in_tool=rng.random()<.78 if in_erp else True
            if in_erp:add(erp,dict(base))
            if in_tool:
                row=dict(base);row['line_id']=f'T{i:07}'
                vat=rng.choice(['0.15','15%','15','','0'])
                factor=Decimal(1) if vat=='0' else Decimal('1.15')
                row.update(amount=str(net*factor),vat=vat,receipt='')
                if i%7==0:row['po']=row['po'].replace('-',' / ')
                if i%19==0:row['description']=direct.replace('o','0',1)
                add(tool,row,in_erp)
                if i%13==0:
                    repeat=dict(row); repeat['line_id']=f'Z{i:07}'
                    add(tool,repeat,True)
        else:
            row=dict(base)
            if kind=='B':
                cur=rng.choice(['USD','EUR','ZAR']);rate={'USD':Decimal(1),'EUR':Decimal('.8'),'ZAR':Decimal(20)}[cur]
                row.update(currency=cur,amount=str(net*rate),rate='' if i%2 or cur=='USD' else str(rate))
                # Impossible optional dates cannot invalidate already-valued USD/line-rate rows.
                if i%23==0 and (cur=='USD' or row['rate']):row['invoice_date']='2024-02-30'
            add(sources[0],row)
    for s in sources:write_csv(raw/s['file'],rendered[s['name']],FIELDS)
    if kind=='C':
        # Onboarding changes mappings only; unseen source column names require no code edit.
        rename={'line_id':'transaction_ref','amount':'net_total','description':'memo','vendor':'third_party','invoice_date':'booked_on'}
        for s in sources:
            rows=rendered[s['name']]
            write_csv(raw/s['file'],[{rename.get(k,k):v for k,v in row.items()} for row in rows],[rename.get(k,k) for k in FIELDS])
            s['columns']={k:[rename.get(vv,vv) for vv in v] if isinstance(v,list) else rename.get(v,v) for k,v in s['columns'].items()}
    config_path=directory/'config.json';config_path.write_text(json.dumps(config,indent=2))
    truth_path=directory/'truth.json';truth_path.write_text(json.dumps(ledger,indent=2))
    (directory/'events.json').write_text(json.dumps(events,indent=2))
    return {'kind':kind,'seed':seed,'events':size,'rows':len(ledger),'raw':str(raw),'config':str(config_path),
            'truth':str(truth_path),'paths':[list(p) for p in paths]}
