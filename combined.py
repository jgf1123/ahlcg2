# -*- coding: utf-8 -*-
"""
Created on Fri Apr  2 23:24:19 2021

@author: jgf11
"""

from csv import DictWriter
from math import sqrt
from random import gauss
from scipy import stats
# from statistics import median
from time import sleep
import collections
import itertools
import json
import pickle
import re
import requests

MAX_DECKLIST_ID = 49173  # latest decklist

# if 'ALLOW', allow all decklists irrespective of taboo
# if 'CURRENT', use most recent taboo and filter out all decklists with cards
#   with lower xp cost than the current taboo
TABOO_FLAG = 'CURRENT'
WEIGHT_BOOL = True  # if True, weight decklists by mythos_weight
SCRAPE_EMPTY = False  # if True, attempt to scrape empty decklist_id

### Scrape decklists
DECKLIST_JSON_PICKLE = 'decklist_json.pickle'
# load already scrapped decklists
# {decklist_id: decklist}
decklist_json = pickle.loads(open(DECKLIST_JSON_PICKLE, "rb").read())

decklist_id = MAX_DECKLIST_ID  # start at latest
print('Scrapping decklists...')
# # don't go earlier than 2019-09-29, when Circle Undone hit arkhamdb
# while decklist_id >= 15614:  
while decklist_id >= 0:
  # if decklist not read in already
  if (decklist_id not in decklist_json
      or SCRAPE_EMPTY and decklist_json[decklist_id] is None):
    try:
      # get API request
      response = requests.get(f'http://arkhamdb.com/api/public/decklist/{decklist_id}.json')
      if response.status_code == 200:  # if response is OK
        if len(response.text) > 0:  # response is not empty
          print(f'{decklist_id}')  # show progress
          decklist_json[decklist_id] = response.json()  # store decklist
        else:
          print(f'{decklist_id} empty')  # show progress
          decklist_json[decklist_id] = None  # mark empty decklist
                    
        # pickle decklist_json after every new decklist
        with open(DECKLIST_JSON_PICKLE, "wb") as djf:
          djf.write(pickle.dumps(decklist_json))
                    
        sleep(gauss(30, 5))  # wait some time so arkhamdb doesn't block us
    # show any API exception
    except requests.exceptions.RequestException as exception:
      print(exception)
  decklist_id -= 1  # next decklist

# Filter out blank decklists
for decklist_id in sorted(decklist_json.keys()):
  decklist = decklist_json[decklist_id]
  if decklist is None:
    decklist_json.pop(decklist_id)
    
decklist_json.pop(44599)  # joke decklist
decklist_json.pop(43839)  # 9 Power Words?

### Scrape cards
CARD_JSON_PICKLE = 'card_json.pickle'
# load already scrapped cards
# {card_code: card}
card_json = pickle.loads(open(CARD_JSON_PICKLE, "rb").read())

print('Scrapping cards...')
for decklist_id, decklist in decklist_json.items():
  # get player and investigator card card_codes
  card_codes = list(decklist['slots'].keys()) + [decklist['investigator_code']]
  for card_code in card_codes:
    if card_code in card_json:  # skip cards we already read
      continue
        
    try:
      # get API response
      response = requests.get(f'http://arkhamdb.com/api/public/card/{card_code}.json')
      if response.status_code == 200:  # if response is OK
        print(card_code)  # show progress
        card_json[card_code] = response.json()  # store card
    # show any API exception
    except requests.exceptions.RequestException as exception:
      print(exception)
            
    # pickle card_json after every new card
    with open(CARD_JSON_PICKLE, "wb") as cjf:
      cjf.write(pickle.dumps(card_json))
            
    sleep(gauss(30, 5))  # wait some time so arkhamdb doesn't block us
    
# some cards have myriad incorrectly marked
for card_code, card in card_json.items():
  if 'Myriad' in card.get('text', ''):
    card['myriad'] = True


### Load taboo file
with open('taboo.json', 'r') as file:  # read in taboo from local file
  taboo_json = json.load(file)
# find id of most recent taboo
MAX_TABOO = max([taboo_dict['id'] for taboo_dict in taboo_json])
    
taboo_dict = collections.defaultdict(dict)  # taboo_id: {card_code: taboo_card}
for taboo in taboo_json:  # for each taboo
  taboo_id = taboo['id']  # get taboo id
  for taboo_card in json.loads(taboo['cards']):  # parse str into json
    card_code = taboo_card['code']  # get card_code
    taboo_dict[taboo_id][card_code] = taboo_card  # save taboo_card
  
  if taboo['id'] == MAX_TABOO:  # if most recent taboo
    # list of card_codes in most recent taboo
    tabooed_cards = [card['code'] for card in json.loads(taboo['cards'])
                      if 'xp' in card or card['text'] == 'Forbidden.']
    
def lookup_taboo(card_code, taboo_id):
  '''Returns taboo card entry for card_code and taboo_id. Returns None if no
  taboo card entry found'''
  if taboo_id in taboo_dict:  # if taboo_id exists
    # if card_code is in taboo_id, return its taboo_card; otherwise return None
    return taboo_dict[taboo_id].get(card_code, None)
  return None  # if taboo_id doesn't exist, return None
  
def lookup_taboo_xp(card_code, taboo_id):
  '''Returns the taboo xp for card_code and taboo_id. Returns 0 if no taboo
  card entry found'''
  taboo_card = lookup_taboo(card_code, taboo_id)  # look up the taboo_card
  if taboo_card is not None:  # if taboo_card exists
    return taboo_card.get('xp', 0)  # return the xp, 0 if not defined
  return 0  # if taboo_card doesn't exist, return 0
  
    
### Merge card codes
# {later_card_code: original_card_code}
merge_cards = {'01683': '03230',  # map revised core set to original campaign/mythos pack
                '01684': '02261',
                '01685': '60227',
                '01686': '06279',
                '01687': '03031',
                '01688': '03234',
                '01689': '51007',
                '01690': '03236',
                '01691': '02308',
                '01692': '05324',
                '01693': '02194',
                '01694': '02158',
                '01695': '02157',
                '60108': '01017',  # map investigator starter to campaign/mythos pack
                '60113': '01023',
                '60119': '01025',
                '60120': '01022',
                '60212': '02020',
                '60218': '02186',
                '60219': '01039',
                '60227': '01685',
                '60307': '01044',
                '60308': '04107',
                '60312': '03194',
                '60313': '03030',
                '60314': '04232',
                '60319': '01053',
                '60405': '02029',
                '60413': '03034',
                '60414': '02153',
                '60417': '04032',
                '60418': '02190',
                '60510': '01075',
                '60514': '04034',
                '60516': '04200',
                '60517': '01079',
                '60518': '02113',
                '60519': '04201',
                '60520': '03114',
                }

def merge_card_code(card_code):
  '''Returns the original card code'''
  # if a revised core set card that duplicates a core set card
  if '01516' <= card_code <= '01603':
    # maps '01516' to '01016'
    original_card_code = (card_code[:2]  # first 2 digits
                          + str(int(card_code[2]) - 5)  # subtract 500
                          + card_code[3:])  # last 2 digits
    return original_card_code
  else:
    # if card_code is in merge_cards, return original_card_code; otherwise
    # it is its own original_card_code, so return it
    return merge_cards.get(card_code, card_code)
        
# Merge decklist card codes
for decklist in decklist_json.values():  # for each decklist
  # for each card_code in decklist
  for card_code in tuple(decklist['slots'].keys()):
    # look up original_card_code of card_code
    original_card_code = merge_card_code(card_code)
    if original_card_code == card_code:  # if same card code
      continue  # we don't need to do anything
        
    num = decklist['slots'].pop(card_code)  # remove existing card code
    # replace with original card code
    try:  # if original_card_code is in decklist, increment its num
      decklist['slots'][original_card_code] += num
    except KeyError:  # otherwise create a new entry with original_card_code
      decklist['slots'][original_card_code] = num
      
# Merge taboo card codes
for taboo_id in sorted(taboo_dict.keys()):  # for each taboo
  taboo = taboo_dict[taboo_id]  # get taboo dict
  for card_code, taboo_card in taboo.items():  # for each card_code in taboo
    # look up original_card_code of card_code
    original_card_code = merge_card_code(card_code)
    if original_card_code == card_code:  # if same card code
      continue  # we don't need to do anything
      
    # copy taboo to new_card_code
    taboo_dict[taboo_id][original_card_code] = taboo_card
    # TIP: keep original taboo just in case
    # taboo_dict[taboo_id].pop(card_code)
    

# tuples of campaign and mythos pack ids
DUNWICH = ('dwl', 'tmm', 'tece', 'bota', 'uau', 'wda', 'litas')
CARCOSA = ('ptc', 'eotp', 'tuo', 'apot', 'tpm', 'bsr', 'dca')
FORGOTTEN = ('tfa', 'tof', 'tbb', 'hote', 'tcoa', 'tdoy', 'sha')
CIRCLE = ('tcu', 'tsn', 'wos', 'fgg', 'uad', 'icc', 'bbt')
DREAM = ('tde', 'sfk', 'tsh', 'dsm', 'pnr', 'wgd', 'woc')
INVESTIGATOR = ('nat', 'har', 'win', 'jac', 'ste')
INNSMOUTH = ('tic', 'itd', 'def', 'hhg', 'lif', 'lod', 'itm')
EDGE = ('eoep', 'eoec')
SCARLET = ('tskp', 'tskc')
HEMLOCK = ('fhvp', 'fhvc')

def pack_to_group(pack_code):  # convert pack code to group number
  '''Returns the group id of pack_code, where the main player cards are in
  increasing order'''
  # if core set or miscellaneous (promo, side story, parallel)
  if pack_code in ('core', 'promo', 'cotr', 'coh', 'lol', 'books', 'iotv', 
                    'tftbw', 'tdg', 'guardians', 'hotel', 'blob', 'rod', 'bob', 
                    'aon', 'dre', 'bad', 'wog', 'btb', 'rcore', 'rtr', 'mtt',
                    'otr', 'ltr', 'ptr', 'rop', 'blbe', 'hfa', 'fof'):
    return 0
  if pack_code in DUNWICH:  # 2017-01: The Dunwich Legacy
    return 10 + DUNWICH.index(pack_code)
  if pack_code in CARCOSA:  # 2017-09: The Path to Carcosa
    return 20 + CARCOSA.index(pack_code)
  if pack_code == 'rtnotz':  # 2018-06: Return to the Night of the Zealot
    return 28
  if pack_code in FORGOTTEN:  # 2018-05: The Forgotten Age
    return 30 + FORGOTTEN.index(pack_code)
  if pack_code == 'rtdwl':  # 2019-01: Return to the Dunwich Legacy
    return 38
  if pack_code in CIRCLE:  # 2019-01: The Circle Undone
    return 40 + CIRCLE.index(pack_code)
  if pack_code == 'rtptc':  # 2019-09: Return to the Path of Carcosa
    return 48
  if pack_code in DREAM:  # 2019-09: The Dream-Eaters
    return 50 + DREAM.index(pack_code)
  if pack_code == 'rttfa':  # 2020-08: Return to the Forgotten Age
    return 58
  if pack_code in INVESTIGATOR:  # 2020-08: Investigator Starter Decks
    return 60
  if pack_code in INNSMOUTH:  # 2020-10: The Innsmouth Conspiracy
    return 70 + INNSMOUTH.index(pack_code)
  if pack_code == 'rttcu':  # 2021-06: Return to the Circle Undone
    return 78
  if pack_code in EDGE:  # 2021-11: The Edge of the Earth
    return 80
  if pack_code in SCARLET:  # ????-??: The Scarlet Keys
    return 90
  if pack_code in HEMLOCK:  # ????-??: The Feast of Hemlock Vale
    return 100
  raise KeyError(pack_code)  # raise error if pack_code not found
    
def pack_to_mythos(pack_code):
  '''Returns the mythos id of pack_code, where the main player cards are in
  increasing order'''
  return pack_to_group(pack_code) // 10

def decklist_group(decklist):
  '''Returns the highest group of any card in the decklist'''
  return max([pack_to_group(card_json[card_code]['pack_code'])
              for card_code in decklist['slots']])

# Count number of player cards added in each mythos
mythos_card_count = collections.Counter()  # {mythos: count of cards}
for card_code, card in card_json.items():
  if 'restrictions' in card:  # ignore personal cards
    if 'investigator' in card['restrictions']:
      continue
  
  # ignore basic weaknesses
  if 'subtype_code' in card and card['subtype_code'] == 'basicweakness':
    continue
  
  # ignore new versions of previous cards
  if merge_card_code(card_code) != card_code:
    continue

  mythos = pack_to_mythos(card['pack_code'])  # look up mythos of card
  mythos_card_count[mythos] += 1  # increment counter of mythos
  
# Count cumulative number of player cards added by this mythos
mythos_card_cumulative = {}  # {mythos: running total of counts}
so_far = 0  # initialize running total
for mythos in sorted(mythos_card_count.keys()):  # for each mythos
  so_far += mythos_card_count[mythos]  # add player cards in this mythos
  mythos_card_cumulative[mythos] = so_far  # store running total
  
### Filter decklists
current_mythos = 4  # !!!: start at Circle Undone
for decklist_id in sorted(decklist_json.keys()):  # for each decklist_id
  decklist = decklist_json[decklist_id]  # get deckllist
  # # !!!: don't use decklists after The Scarlet Keys yet
  # if decklist_group(decklist) >= 100:
  #   decklist_json.pop(decklist_id)
  #   continue
    
  # # !!!: Remove decklists that don't use Edge of the Earth
  # if decklist_group(decklist) < 80:
  #   decklist_json.pop(decklist_id)
  #   continue
    
  # # Remove decklists that don't use the most current mythos at the time
  # # find highest group in decklist
  # group = decklist_group(decklist)
  # mythos = group // 10
  # current_mythos = max(mythos, current_mythos)
  
  # if mythos < current_mythos:  # if not using most current mythos
  #   decklist_json.pop(decklist_id)
  
  # Remove decklists that have upgraded versions
  if decklist['next_deck'] is not None:
    decklist_json.pop(decklist_id)
    continue
  
  # if we only want decklists consistent with the current taboo
  if TABOO_FLAG == 'CURRENT':
    taboo_id = decklist['taboo_id']  # taboo_id of this decklist
    if taboo_id == MAX_TABOO:  # if already using current taboo
      continue  # don't pop this decklist
    
    pop_flag = False  # init whether to pop this decklist
    for card_code in decklist['slots']:  # for each card_code in decklist
      # if taboo_id has lower xp cost than MAX_TABOO does
      if (lookup_taboo_xp(card_code, taboo_id)
          < lookup_taboo_xp(card_code, MAX_TABOO)):
        pop_flag = True  # pop this decklist
        break  # don't need to check remaining cards
        
    if pop_flag:  # if at least one card found inconsistent with current taboo
      decklist_json.pop(decklist_id)  # remove this decklist
  
# # Count decks in each mythos
# mythos_deck_count = collections.Counter()
# for decklist in decklist_json.values():
#   if decklist is None:
#     continue
  
#   # find highest group in decklist
#   group = decklist_group(decklist)
#   mythos = group // 10
#   mythos_deck_count[mythos] += 1

# # Calculate decklist weight of each mythos
# mythos_weight = {}  # how much do we weight decklists in each mythos
# for mythos in sorted(mythos_card_count.keys()):
#   if mythos <= 4:  # <= Circle Undone
#     deck_count = mythos_deck_count[4]  # use Circle Undone
#   elif mythos >= 10:  # !!!: for new mythos
#     deck_count = mythos_deck_count[9]  # use Scarlet Keys
#   else:
#     deck_count = mythos_deck_count[mythos]
      
#   mythos_weight[mythos] = (mythos_card_cumulative[mythos] ** 2) / (deck_count ** 2)
    
# Count the number of cards from each mythos in all decklists
# {mythos: count of cards}
mythos_decklist_card_count = collections.Counter()
for decklist in decklist_json.values():  # for each decklist
  # for each card_code in decklist
  for card_code, num in decklist['slots'].items():
    # look up mythos of card_code
    mythos = pack_to_mythos(card_json[card_code]['pack_code'])
    mythos_decklist_card_count[mythos] += num  # increment counter of mythos
    
# Calculate decklist weight of each mythos
# how much do we weight decklists in each mythos
mythos_weight = {}  # {mythos: weight}
for mythos in sorted(mythos_card_count.keys()):  # for each mythos
  # if mythos <= 4:  # if before or in Circle Undone
  #   decklist_card_count = mythos_decklist_card_count[4]  # use Circle Undone
  # elif mythos >= 10:  # !!!: for new mythos
  #   decklist_card_count = mythos_decklist_card_count[9]  # use Scarlet Keys
  # else:
  #   decklist_card_count = mythos_decklist_card_count[mythos]
  
  if mythos > 9:  # !!!: if after Scarlet Keys
    decklist_card_count = mythos_decklist_card_count[9]  # use Scarlet Keys
  else:
    decklist_card_count = mythos_decklist_card_count[mythos]
      
  mythos_weight[mythos] = mythos_card_cumulative[mythos] ** 2 / (decklist_card_count ** 2)
  
# !!!: normalize so mythos 9 (The Scarlet Keys) is 1
norm = mythos_weight[9]
mythos_weight = {mythos: weight / norm
                  for mythos, weight in mythos_weight.items()}


# look for upgrades that have index and xp
UPGRADE_PATTERN = re.compile('\d+\|\d+.*')

def parse_customizable(customizable_string):
  # print(customizable_string)
  # example: customizable_string = '0|1,3|1,6|5,1|1,4|2'
  # example: ['0|1', '3|1', '6|5', '1|1', '4|2']
  upgrade_list = customizable_string.split(',')
  # 'x|y': index of upgrade on card is x; y is xp cost of upgrade
  # example: [['0', '1'], ['3', '1'], ['6', '5'], ['1', '1'], ['4', '2']]
  upgrade_list = [upgrade.split('|') for upgrade in upgrade_list
                  if UPGRADE_PATTERN.match(upgrade)]
  indices_list = [upgrade[0] for upgrade in upgrade_list
                  if int(upgrade[1]) > 0]
  indices_list.sort()  # put in order
  indices_str = ''.join(indices_list)  # example: '01346'
  xp_cost = sum([int(upgrade[1]) for upgrade in upgrade_list])
  return indices_str, xp_cost

def calc_card_code_xp(card_code):
  card_dict = card_json[card_code]  # lookup the card
  card_xp = card_dict.get('xp', 0)  # XP cost of card_code
  # if card is exceptional
  exceptional = card_dict.get('exceptional', False)
  
  # check if card is in latest taboo list
  if TABOO_FLAG == 'CURRENT' and card_code in tabooed_cards:
    card_taboo = lookup_taboo(card_code, MAX_TABOO)
    if 'xp' in card_taboo:  # modify XP if necessary
      card_xp += card_taboo['xp']
    if 'exceptional' in card_taboo:  # overwrite taboo if necessary
      exceptional = card_taboo['exceptional']
      
  if exceptional:  # double XP if exceptional
    card_xp *= 2
    
  return card_xp

def decklist_xp(decklist):
  '''Returns the XP cost of the decklist'''
  # taboo_id = decklist['taboo_id']  # taboo_id of decklist
  
  xp = 0  # running total XP of decklist
  for card_code, num in decklist['slots'].items():
    card_dict = card_json[card_code]  # lookup the card
    card_code_xp = calc_card_code_xp(card_code)
        
    if card_dict.setdefault('myriad', False):  # if myriad, only add XP once
      xp += card_code_xp
    else:  # otherwise add XP for each copy
      xp += card_code_xp * num
      
  meta = decklist['meta']
  if meta != '':  # skip if no meta
    customizable_cards = json.loads(decklist['meta'])
    # example: {'cus_09040': '0|1,3|1,6|5,1|1,4|2'}
    for key, customizable_string in customizable_cards.items():
      if key.startswith('cus_'):  # for customizable cards
        indices, customization_xp = parse_customizable(customizable_string)
        xp += customization_xp  # add cost once
      
  if '08125' in decklist['slots']:  # if In the Thick of It
    xp = max(0, xp - 3)  # remove up to 3 XP
    
  if decklist_investigator_name(decklist) == 'Kymani Jones':
    xp = max(0, xp - 5)  # remove up to 5 xp
          
  return xp

def decklist_investigator_name(decklist):
  '''Returns the investigator name, including parallel front'''
  investigator_name = decklist['investigator_name']
  if len(decklist['meta']) > 0:
    meta = json.loads(decklist['meta'])
    if 'alternate_front' in meta and meta['alternate_front'] >= '90000':
      return f'Parallel {investigator_name}'
  return investigator_name
      
    
investigator_names = set([decklist_investigator_name(decklist) for decklist 
                          in decklist_json.values() if decklist is not None])
# investigator_codes = {decklist_investigator_name(decklist): decklist['investigator_code']
#                       for decklist in decklist_json.values()
#                       if decklist is not None}
    

# Marie Lambeau Promo 2016
# Jenny Barnes Promo 2017-10
# Ire of the Void, Norman Withers Promo 2017-12
# The Night's Usurper 2018
# Roland Banks Promo 2018-02
# To Fight the Black Wind, Carolyn Fern Promo 2018-04
# Return of Night of the Zealot 2018-04
# The Deep Gate, Silas Marsh Promo 2018-06
# The Eternal Slumber 2018-08
# Guardians of the Abyss 2018-11
# The Blob That Ate Everything 2019
# Return to Dunwich Legacy 2019-01
# Return to the Path to Carcosa 2019-09
# Murder at the Excelsior Hotel 2019-10
# Read or Die 2020-05
# Blood of Baalshandor 2020-06
# Return to the Forgotten Age 2020-08
# All or Nothing 2020-08
# Investigator Starters 2020-08
# The Meddling of Meowlathotep: Scenario Pack 2020-09
# Dark Revelations 2020-11
# Bad Blood 2020-12
# War of the Outer Gods 2020-12
# By the Book 2021-06
# Return to the Circle Undone 2021-08
# Revised Core Set 2021-10
# Red Tide Rising 2021-12

# (Vaguely) Chronological order of packs
pack_order = ('core',  # 2016-11
              'rcore',
              'promo',  # 2016 ..
              'cotr',  # 2016-11
              'coh',   # 2016-12
              'dwl', 'tmm', 'tece', 'bota', 'uau', 'wda', 'litas',  # 2017-01 .. 2017-07
              'lol', # 2017-08
              'ptc', 'eotp', 'tuo', 'apot', 'tpm', 'bsr', 'dca', # 2017-08 .. 2018-03
              'books', # 2017-10 .. 2020-11
              'iotv',  # 2017-12
              'rtnotz',  # 2018-04-27
              'tftbw',  # 2018-04-29
              'tfa', 'tof', 'tbb', 'hote', 'tcoa', 'tdoy', 'sha', # 2018-05 .. 2018-11
              'tdg',  # 2018-06
              'guardians', # 2018-11
              'rtdwl', # 2019-01
              'tcu', 'tsn', 'wos', 'fgg', 'uad', 'icc', 'bbt', # 2019-01 .. 2019-07
              'rtptc', # 2019-09
              'tde', 'sfk', 'tsh', 'dsm', 'pnr', 'wgd', 'woc', # 2019-09 .. 2020-04
              'blob', 'hotel', 'rod', 'bob', 'rttfa', 'aon', # 2019-10 .. 2020-08
              'nat', 'har', 'win', 'jac', 'ste', # 2020-08
              'tic', 'itd', 'def', 'hhg', 'lif', 'lod', 'itm',  # 2020-10 .. 2021-05
              'dre', 'bad', 'wog', 'btb', 'rttcu',  # 2020-11 .. 2021-08
              'eoep', 'eoec',  # 2021-11
              'rtr',  # 2021-12
              'tskp', 'tskc',
              'mtt', 'otr', 'ltr', 'ptr', 'rop',
              'fhvp', 'fhvc')  # ???

### Calculate number of slots
# INVESTIGATORS_TO_BUILD = ['Finn Edwards']

for zero_xp in (True, False):
  if zero_xp:
    print('\n0XP slots...')
  else:
    print('\nAny XP slots...')

  slot_table = {}
  for investigator_name in investigator_names:
    # slot_table[investigator_name] = collections.defaultdict(list)
    slot_table[investigator_name] = collections.Counter()
      
  slot_tup = ('Accessory', 'Ally', 'Arcane', 'Body', 'Hand', 'Tarot')
  
  for decklist_id, decklist in decklist_json.items():
    # if need to filter out non-zero xp decklists
    if zero_xp and decklist_xp(decklist) > 0:
      continue
    
    # find highest group in decklist
    group = max([pack_to_group(card_json[card_code]['pack_code'])
                  for card_code in decklist['slots']])
    # if group < 40:  # need at least one card from Circle Undone or later
    #     continue
    mythos = group // 10
    weight = mythos_weight[mythos]
    
    investigator_name = decklist_investigator_name(decklist)
    
    # Count how many of each slot the decklist uses
    slot_tally = collections.Counter()
    for card_code, num in decklist['slots'].items():
      card = card_json[card_code]
      try:
        slot = card['slot']
      except KeyError:  # skip cards without slot attribute
        continue
      
      if card_code == '08127':  # special case: sled dog
        slot_tally['Ally'] += num / 2
        continue
      
      slot_split = slot.split('. ')
      for slot in slot_split:        
        if slot.endswith(' x2'):
          slot = slot[:-3]  # remove ' x2'
          num *= 2  # take twice as many slots
        
        slot_tally[slot] += num
        
    # save to table
    # for slot in slot_tup:
    #     slot_table[investigator_name][slot].append(slot_tally[slot])
    
    # For arithmetic mean calculation
    for slot in slot_tup:
      slot_table[investigator_name][slot] += slot_tally[slot] * weight
    slot_table[investigator_name]['weight'] += weight
  
  # def interpolated_median(x):
  #     '''For elements with the same value V, does a linear interpolation between
  #     (V - 0.5) and (V + 0.5) before returning the median'''
  #     copy = list(x)  # make a copy
  #     for element in set(copy):  # for each unique value
  #         indices = [i for i, e in enumerate(copy) if e == element]
  #         num_element = len(indices)
  #         for n, i in enumerate(indices):
  #             copy[i] = element + (2 * n + 1 - num_element) / (2 * num_element)
              
  #     return median(copy)
  
  # # Calculate the median number of each slot
  # slot_median = {}
  # for investigator_name in slot_table:
  #     slot_median[investigator_name] = {}
  #     for slot in slot_tup:
  #         slot_median[investigator_name][slot] = \
  #             interpolated_median(slot_table[investigator_name][slot])
  
  if zero_xp:
    SLOT_FILE = 'slot_0xp.csv'
  else:
    SLOT_FILE = 'slot.csv'
  with open(SLOT_FILE, 'w', newline='', encoding="utf-8") as csvfile:
    # # For median calculation
    # writer = DictWriter(csvfile, delimiter=',',
    #                     fieldnames=['Investigator', 'Slot', 'Median'])
    # writer.writeheader()
    # for investigator_name, slot_dict in slot_median.items():
    #     for slot, med in slot_dict.items():
    #         writer.writerow({'Investigator': investigator_name,
    #                           'Slot': slot,
    #                           'Median': med})
    
    # For arithmetic mean calculation
    writer = DictWriter(csvfile, delimiter=',',
                        fieldnames=['Investigator', 'Slot', 'Mean'])
    writer.writeheader()
    for investigator_name, counter in slot_table.items():
      if counter['weight'] == 0:
        continue
      
      for slot in slot_tup:
        writer.writerow({'Investigator': investigator_name,
                          'Slot': slot,
                          'Mean': counter[slot] / counter['weight']})


# DECKLIST_JSON_PICKLE = 'decklist_json.pickle'
# decklist_json = pickle.loads(open(DECKLIST_JSON_PICKLE, "rb").read())

# CARD_JSON_PICKLE = 'card_json.pickle'
# card_json = pickle.loads(open(CARD_JSON_PICKLE, "rb").read())

def max_allowed(card_code):
  '''Returns the maximum number of the card allowed in a deck'''
  if card_code == '03012':  # Painted World
    return 3
  
  if card_code == '08127':  # Sled Dog
    return 4
  
  card = card_json[card_code]
  if card.setdefault('myriad', False):  # if myriad
    return 3
  
  # if card is exceptional
  exceptional = card.setdefault('exceptional', False)
      
  # check if card is taboo'd
  if TABOO_FLAG == 'CURRENT':
    card_taboo = lookup_taboo(card_code, MAX_TABOO)
    # overwrite with taboo if necessary
    if card_taboo is not None and 'exceptional' in card_taboo:
      exceptional = card_taboo['exceptional']
      
  # max 1 if card is exceptional otherwise default to 2
  return 1 if exceptional else 2


Card = collections.namedtuple('Card', field_names=["code", "xp", "indices"])

class Investigator:
  def __init__(self):
    self.cards = collections.defaultdict(lambda: [collections.Counter(),
                                                  collections.Counter(),
                                                  collections.Counter(),
                                                  collections.Counter()])
    self.groups = collections.Counter()
    # self.groups_ignore_taboo = collections.Counter()
      
  def add_cards(self, card, num, group):
    '''Records num of card from a decklist with group'''
    for n in range(num):
      self.cards[card][n][group] += 1
          
  def count_cards(self, card, num, min_group, weighted=False):
    '''Return the number of decklists with at least min_group with at least
    num of card'''
    if weighted:  # apply mythos weight
      return sum([count * mythos_weight[group // 10]
                  for group, count in self.cards[card][num - 1].items()
                  if group >= min_group])
    
    # use weight = 1
    return sum([count
                for group, count in self.cards[card][num - 1].items()
                if group >= min_group])
      
  def count_groups(self, min_group, weighted=False):
    '''Returns the number decklists with at least min_group.'''
    group_dict = self.groups
    if weighted:  # apply mythos weight
      return sum([count * mythos_weight[group // 10]
                  for group, count in group_dict.items()
                  if group >= min_group])
    
    # use weight = 1
    return sum([count for group, count in group_dict.items()
                if group >= min_group])
    
Sort_tuple = collections.namedtuple('Sort_tuple', ['key', 'sortby'])

for zero_xp in (False, True):
# for zero_xp in (True, ):
  if zero_xp:
    print('\n0XP decklists...')
  else:
    print('\nAny XP decklists...')
  
  #investigator_decklists = {}  # list of decklist_ids for each investigator
  investigators = collections.defaultdict(Investigator)
  for decklist_id, decklist in decklist_json.items():
    if decklist is None:  # skip deleted decklists
      continue
    
    if zero_xp and decklist_xp(decklist) > 0:  # only looking at 0xp decks
      continue
      
    investigator_name = decklist_investigator_name(decklist)
    # if investigator_name not in INVESTIGATORS_TO_BUILD:
    #   continue
    # # record that this investigator has a decklist with this group number
    # investigators[investigator_name].groups_ignore_taboo[group] += 1
    
    group = decklist_group(decklist)  # find highest group in decklist
    # if group < 40:  # need at least one card from Circle Undone or later
    #     continue
    mythos = group // 10
    weight = mythos_weight[mythos]
    
    # record that this investigator has a decklist with this group number
    investigators[investigator_name].groups[group] += 1
    # investigators[investigator_name].groups[group] += weight
    
    # Add the decklist's cards to the Investigator object
    for card_code, num in decklist['slots'].items():
      card_dict = card_json[card_code]
      # if 'restrictions' in card:  # ignore personal cards
      #     continue

      # ignore basic weaknesses
      if card_dict['type_code'] in ('treachery', 'enemy'):
        continue
      
      # check for customizable cards
      meta = decklist['meta']
      if meta != '':
        customizable_cards = json.loads(meta)
        # example: {'cus_09040': '0|1,3|1,6|5,1|1,4|2'}
        try:
          customizable_string = customizable_cards[f'cus_{card_code}']
          # print(f'{decklist_id} {meta}')
          indices, customization_xp = parse_customizable(customizable_string)
          card = Card(code=card_code,
                      xp=calc_card_code_xp(card_code) + customization_xp,
                      indices=indices)
        except KeyError:
          card = Card(code=card_code,
                      xp=calc_card_code_xp(card_code),
                      indices=None)
      else:
        card = Card(code=card_code,
                    xp=calc_card_code_xp(card_code),
                    indices=None)
      
      # record that this investigator has this card num times in a
      # decklist with this group number
      investigators[investigator_name].add_cards(card, num, group)
  
  if zero_xp:
    CSV_FILE = 'decklist3_0xp.csv'    
  else:
    CSV_FILE = 'decklist3.csv'
  with open(CSV_FILE, 'w', newline='', encoding="utf-8") as csvfile:
    writer = DictWriter(csvfile, delimiter=',',
                        fieldnames=['Investigator', 'Pack', 'Card_Code',
                                    'Card', 'Index', 'Score', 'Mean', 'Slot',
                                    'Faction', 'Decks', 'Recent Decks'])
    writer.writeheader()
    
    # for each investigator
    for investigator_name in sorted(investigator_names):
      # if investigator_name not in INVESTIGATORS_TO_BUILD:
      #   continue
      
      investigator = investigators[investigator_name]
      print(investigator_name)
      
      # !!!: number of decklists made since Scarlet Keys
      recent_decks = investigator.count_groups(90, weighted=WEIGHT_BOOL)
      
      # running total of card scores
      card_scores = collections.defaultdict(lambda: 0)
      # scores out of what maximum
      card_max = collections.Counter()
      # for each pair of cards
      for card_AB in itertools.combinations(investigator.cards, 2):
        # most recent group
        group = max([pack_to_group(card_json[card.code]['pack_code'])
                      for card in card_AB])
        # number of decklists where both cards were available
        # count_decklists = investigator.count_groups(group)
        count_decklists = investigator.count_groups(group,
                                                    weighted=WEIGHT_BOOL)
        if count_decklists <= 1:
          continue
        
        # maximum number of each card allowed
        max_A, max_B = map(max_allowed, [card.code for card in card_AB])
        
        for num_AB in itertools.product(range(1, max_A + 1),
                                        range(1, max_B + 1)):
          # number of decklists with (card_code, num)
          count_AB = [investigator.count_cards(card, num, group,
                                                weighted=WEIGHT_BOOL)
                      for card, num in zip(card_AB, num_AB)]
          # mean of Bernoulli distribution
          mean_AB = [count / count_decklists for count in count_AB]
          # squared standard error
          sserr_AB = [(mean - mean**2) / (count_decklists - 1)
                      for mean in mean_AB]
          
          # Welsh's t-test
          try:
            # t-statistic
            t_stat = (mean_AB[0] - mean_AB[1]) / sqrt(sum(sserr_AB))
            # degrees of freedom
            nu = (sum(sserr_AB)**2
                  / sum([sserr**2 / (count_decklists - 1)
                          for sserr in sserr_AB]))
            p = stats.t.cdf(t_stat, df=nu)
          except ZeroDivisionError:
            mean_A, mean_B = mean_AB
            if mean_A > mean_B:  # if mean_A > mean_B
              p = 1
            elif mean_A < mean_B:  # if mean_A < mean_B
              p = 0
            else:
              p = 0.5
          
          # add card scores
          card_A, card_B = card_AB
          num_A, num_B = num_AB
          card_scores[(card_A, num_A)] += p
          card_scores[(card_B, num_B)] += 1 - p
          
          for card_num in zip(card_AB, num_AB):
            card_max[card_num] += 1
                  
      # sort by decreasing score
      score_list = [Sort_tuple(key=card_num,
                                sortby=score / card_max[card_num])
                    for card_num, score in card_scores.items()]
      score_list.sort(key=lambda t:t.sortby, reverse=True)
      
      for card_num, score in score_list:
        card, num = card_num
        card_xp = card.xp
        
        card_dict = card_json[card.code]
        myriad = card_dict.setdefault('myriad', False)
        
        card_name = card_dict['name']
        try: # add subname if any
          card_name += f": {card_dict['subname']}"
        except KeyError:
          pass
        
        if card.indices is not None:  # if customizable indices
          card_name += f' {card.indices}'
        
        if card_xp > 0:
          if myriad:
            card_name += f' ({card_xp} Myriad)'
          else:  # double xp from exceptional included
            card_name += f' ({card_xp})'
        
        # get card slot, default to blank
        slot = card_dict.setdefault('slot', '')
            
        pack_code = card_dict['pack_code']
        # pack_hash = f'{pack_order.index(pack_code):02d}-{pack_code}'
        pack_hash = f'{pack_to_group(pack_code):02d}-{pack_code}'
        card_group = pack_to_group(pack_code)
        
        # number of deck
        num_decks = investigator.count_groups(card_group,
                                              weighted=WEIGHT_BOOL)
        # # decks ignoring taboo
        # num_decks_taboo = investigator.count_groups(card_group,
        #                                             ignore_taboo=True,
        #                                             weighted=WEIGHT_BOOL)
        mean = investigator.count_cards(card, num, card_group, weighted=WEIGHT_BOOL) / num_decks
            
        writer.writerow({'Investigator': investigator_name,
                          'Pack': pack_hash,
                          'Card_Code': card.code,
                          'Card': card_name,
                          'Index': num,
                          'Score': score,
                          'Mean': mean,
                          'Slot': slot,
                          'Faction': card_dict['faction_name'],
                          'Decks': num_decks,
                          'Recent Decks': recent_decks})

# Find number of Silas and Norman decklists since their campaigns came out
min_decklist_tic = min([
  decklist_id for decklist_id, decklist in decklist_json.items()
  if decklist is not None
  and decklist['investigator_name'] in ('Amanda Sharpe', 'Dexter Drake',
                                        'Sister Mary', 'Trish Scarborough')])
num_silas = sum([mythos_weight[decklist_group(decklist) // 10] if WEIGHT_BOOL else 1
                  for decklist_id, decklist in decklist_json.items()
                  if decklist is not None
                  and decklist['investigator_name'] == 'Silas Marsh'
                  and decklist_id >= min_decklist_tic
                  and decklist_xp(decklist) == 0])
print(f'Silas {num_silas}')

min_decklist_eoe = min([
  decklist_id for decklist_id, decklist in decklist_json.items()
  if decklist is not None
  and decklist['investigator_name'] in ('Bob Jenkins', 'Daniela Reyes',
                                        'Lily Chen', 'Monterey Jack')])
num_norman = len([mythos_weight[decklist_group(decklist) // 10] if WEIGHT_BOOL else 1
                  for decklist_id, decklist in decklist_json.items()
                  if decklist is not None
                  and decklist['investigator_name'] == 'Norman Withers'
                  and decklist_id >= min_decklist_eoe
                  and decklist_xp(decklist) == 0])
print(f'Norman {num_norman}')