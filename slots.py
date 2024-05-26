# -*- coding: utf-8 -*-
"""
Created on Fri Sep 11 20:00:16 2020

@author: jgf1123
"""

import pickle
from statistics import median

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

DECKLIST_JSON_PICKLE = 'decklist_json.pickle'
decklist_json = pickle.loads(open(DECKLIST_JSON_PICKLE, "rb").read())

CARD_JSON_PICKLE = 'card_json.pickle'
card_json = pickle.loads(open(CARD_JSON_PICKLE, "rb").read())

slot_table = {}
slot_list = ['Accessory', 'Ally', 'Arcane', 'Body', 'Hand', 'Tarot']
for slot in slot_list:
    slot_table[slot] = {}

for decklist_id, decklist in decklist_json.items():
    if decklist is None:  # skip deleted decklists
        continue
    
    if decklist_xp(decklist) > 0:  # only looking at 0xp decks
        continue
    
    # if decklist has non-Taboo Machete
    if decklist['taboo_id'] is None and '01020' in decklist['slots']:
        continue
    
    investigator_name = decklist['investigator_name']
    
    slot_tally = {}
    for slot in slot_list:
        slot_tally[slot] = 0
    
    for card_code, num in decklist['slots'].items():
        card = card_json[card_code]
        try:
            slot = card['slot']
        except KeyError:  # skip cards without slot attribute
            continue
        
        slot_split = slot.split('. ')
        for slot in slot_split:        
            if slot.endswith(' x2'):
                slot = slot[:-3]  # remove ' x2'
                num *= 2  # take twice as many slots
            
            slot_tally[slot] += num
            
    for slot, tally in slot_tally.items():
        try:
            slot_table[slot][investigator_name].append(tally)
        except KeyError:
            slot_table[slot][investigator_name] = [tally]
            
SLOT_FILE = 'slot.csv'
with open(SLOT_FILE, 'w') as fh:
    fh.write('Investigator,Slot,Median\n')
    for slot, slot_dict in slot_table.items():
        for investigator_name, tallies in slot_dict.items():
            fh.write('{},{},{}\n'.format(investigator_name, slot, median(tallies)))