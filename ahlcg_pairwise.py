# -*- coding: utf-8 -*-
"""
Created on Fri Sep  4 14:57:26 2020

@author: jgf1123
"""

import math
import pickle
from scipy import stats

#class Decklist:
#    def __init__(self, json):
#        self.decklist_id = json['id']
#        self.date_update = json['date_update']  # grab date
#        self.investigator_code = int(json['investigator_code'])
#        
#        self.slots = {}
#        for card_code, num in json['slots'].items():
#            self.slots[card_code] = num
#            
class Card:
    def __init__(self):
#        self.code = json['code']
#        self.pack_code = json['pack_code']
#        self.type_code = json['type_code']
#        self.faction_code = json['faction_code']
#        self.name = json['name']
#        #self.cost = json['cost']
#        try:
#            self.xp = json['xp']
#        except KeyError:
#            self.xp = None
        
        self.reset()
        
    def add(self, investigator_name, count):
        try:
            for c in range(count):
                self.counts[investigator_name][c] += 1
        except KeyError:
            self.counts[investigator_name] = [0, 0, 0]
            for c in range(count):
                self.counts[investigator_name][c] = 1
    
    def reset(self):
        self.counts = {}

class Investigator:
    def __init__(self):
        self.counts = {}
        self.groups = [0] * (MAX_GROUP + 1)
        
    def add_card(self, card_code, num):
        try:
            for n in range(num):
                self.counts[card_code][n] += 1
        except KeyError:
            self.counts[card_code] = [0, 0, 0, 0]
            for n in range(num):
                self.counts[card_code][n] = 1
                
    def add_group(self, group):
        for g in range(group + 1):
            self.groups[g] += 1

def decklist_xp(decklist):
    # TODO: account for myriad
    xp = 0
    for card_code, num in decklist['slots'].items():
        card = card_json[card_code]
        try:
            xp += card['xp'] * num
        except KeyError:  # ignore cards with no xp
            continue
    return xp

dunwich = ('dwl', 'tmm', 'tece', 'bota', 'uau', 'wda', 'litas','rtdwl')
carcosa = ('ptc', 'eotp', 'tuo', 'apot', 'tpm', 'bsr', 'dca', 'rtptc')
forgotten = ('tfa', 'tof', 'tbb', 'hote', 'tcoa', 'tdoy', 'sha', 'rttfa')
circle = ('tcu', 'tsn', 'wos', 'fgg', 'uad', 'icc', 'bbt')
dream = ('tde', 'sfk', 'tsh', 'dsm', 'pnr', 'wgd', 'woc')
starter = ('nat', 'har', 'win', 'jac', 'ste')
innsmouth = ('tic', 'itd', 'def', 'hhg', 'lif', 'lod', 'itm')
edge = ('eoep', 'eoec')

# Table to convert pack code to group number
def pack_to_group(pack_code):
    if pack_code in ('core', 'rcore', 'cotr', 'coh', 'books', 'promo', 'rtnotz', 'lol', 'guardians', 'blob', 'hotel', 'rod', 'aon', 'wog', 'rttcu'):
        return 0
    if pack_code in dunwich:
        return 10 + dunwich.index(pack_code)
    if pack_code in carcosa:
        return 20 + carcosa.index(pack_code)
    if pack_code in forgotten:
        return 30 + forgotten.index(pack_code)
    if pack_code in circle:
        return 40 + circle.index(pack_code)
    if pack_code in dream:
        return 50 + dream.index(pack_code)
    if pack_code in starter:
        return 60 + starter.index(pack_code)
    if pack_code in innsmouth:
        return 70 + innsmouth.index(pack_code)
    if pack_code in edge:
        return 80
    raise KeyError(pack_code)
MAX_GROUP = 80  # TODO: hard-coded max group

# (Vaguely) Chronological order of packs
pack_order = ('core', 'cotr', 'coh', 'promo', # .. 2017-02
              'dwl', 'tmm', 'tece', 'bota', 'uau', 'wda', 'litas', # 2017-01 .. 2017-07
              'ptc', 'eotp', 'tuo', 'apot', 'tpm', 'bsr', 'dca', # 2017-09 .. 2018-03
              'books', 'rtnotz', # 2017-10 .. 2020-06
              'tfa', 'tof', 'tbb', 'hote', 'tcoa', 'tdoy', 'sha', # 2018-05 .. 2018-11
              'lol', 'guardians', 'rtdwl', # 2018-01 .. 2019-01
              'tcu', 'tsn', 'wos', 'fgg', 'uad', 'icc', 'bbt', # 2019-01 .. 2019-07
              'rtptc', # 2019-09
              'tde', 'sfk', 'tsh', 'dsm', 'pnr', 'wgd', 'woc', # 2019-09 .. 2020-04
              'blob', 'hotel', 'rod', 'rttfa', 'aon', # 2019-11 .. 2020-08
              'nat', 'har', 'win', 'jac', 'ste', # 2020-08
              'tic', 'itd', 'def', 'hhg', 'lif', 'lod', 'itm',  #2020-10 .. ???
              'wog',  'rttcu',  'rcore', # 2020-12 .. 2021-10
              'eoep', 'eoec'  # 2021-11
              )

DECKLIST_JSON_PICKLE = 'decklist_json.pickle'
decklist_json = pickle.loads(open(DECKLIST_JSON_PICKLE, "rb").read())

CARD_JSON_PICKLE = 'card_json.pickle'
card_json = pickle.loads(open(CARD_JSON_PICKLE, "rb").read())

#investigator_decklists = {}  # list of decklist_ids for each investigator
investigators = {}
for decklist_id, decklist in decklist_json.items():
    if decklist is None:  # skip deleted decklists
        continue
    
#    if decklist_xp(decklist) > 0:  # only looking at 0xp decks
#        continue
    
    investigator_name = decklist['investigator_name']
    group = 0
    for card_code, num in decklist['slots'].items():
        card = card_json[card_code]
        if 'restrictions' in card:  # ignore personal cards
            continue

        if card['type_code'] in ('treachery', 'enemy'):  # ignore basic weaknesses
            continue
        
        # Chained cards
        if card_code in ('01020', '01050', '02026', '02152', '02187', '02189',
                         '02193', '05159') and decklist['taboo_id'] is None:
            continue
        
        # find max group among cards
        group = max(group, pack_to_group(card_json[card_code]['pack_code']))
        
        try:  # add cards
            investigators[investigator_name].add_card(card_code, num)
        except KeyError:
            investigators[investigator_name] = Investigator()
            investigators[investigator_name].add_card(card_code, num)
    
    investigators[investigator_name].add_group(group)

CSV_FILE = 'decklist3.csv'
with open(CSV_FILE, 'w') as cf:
#    min_log = -453.3797627972774
    
    cf.write('Investigator|Pack|Card|Index|Score|Mean|Slot|Faction|Decks\n')
    for investigator_name, investigator in investigators.items():  # for each investigator
        print(investigator_name)
        
        card_dict = {}
        for card_code, count_list in investigator.counts.items():  # for each card
            group = pack_to_group(card_json[card_code]['pack_code'])
            num_decks = investigator.groups[group]  # number of decklists with this group
            if num_decks < 2:  # only if in at least 2 decklists
                continue
            
            for num_include, count in enumerate(count_list):  # for 1st, 2nd, 3rd copy of card
                if count < 1:
                    continue
                
                mean = count / num_decks
                if mean < 0.02:
                    continue
                svar = (mean - mean**2) * num_decks / (num_decks - 1)
                card_dict[(card_code, num_include)] = {'mean':mean, 'svar':svar, 'N':num_decks, 'score':0}
    
        tuples = tuple(card_dict.keys())
        num_tuples = len(tuples)
        for a, tup_a in enumerate(tuples[:-1]):  # for each pair of tuples
            for tup_b in tuples[a + 1:]:
                A = card_dict[tup_a]
                B = card_dict[tup_b]
                v_A = A['svar'] / A['N']
                v_B = B['svar'] / B['N']
                
                try:
                    # t-statistic
                    t_stat = (A['mean'] - B['mean']) / math.sqrt(v_A + v_B)
                    # degrees of freedom
                    nu = (v_A + v_B)**2 / (v_A**2 / (A['N'] - 1) + v_B**2 / (B['N'] - 1))
                    p = stats.t.cdf(t_stat, df=nu)
                except ZeroDivisionError:
                    if A['mean'] > B['mean']:
                        p = 1
                    elif A['mean'] < B['mean']:
                        p = 0
                    else:
                        p = 0.5
                    
                A['score'] += p
                B['score'] += 1 - p
                
        score_list = [(tup, dct['score'] / (num_tuples - 1)) for tup,dct in card_dict.items()]
        score_list.sort(key=lambda t:t[1], reverse=True)
        
        for tup,score in score_list:
            card_code,card_index = tup
            card = card_json[card_code]
            
            card_name = card['name']
            try: # add subname if any
                card_name += ': {}'.format(card['subname'])
            except KeyError:
                pass
            try:
                if card['xp'] is not None and card['xp'] > 0:
                    card_name += ' ({})'.format(card['xp'])
            except KeyError: # if no xp attribute
                pass
            
            try:
                slot = card['slot']
            except KeyError:
                slot = ''
                
            pack_code = card['pack_code']
            pack_hash = '{:02d}-{}'.format(pack_order.index(pack_code), pack_code)
            card_group = pack_to_group(pack_code)
            
            num_decks = investigator.groups[card_group]
            mean = investigator.counts[card_code][card_index] / num_decks
                
            cf.write('{}|{}|{}|{}|{}|{}|{}|{}|{}\n'.format(investigator_name,
                pack_hash, card_name, card_index + 1, score, mean, slot,
                card['faction_name'], num_decks))
            
#print(min_log)