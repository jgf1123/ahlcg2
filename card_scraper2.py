# -*- coding: utf-8 -*-
"""
Created on Fri Sep  4 13:36:35 2020

@author: jgf1123
"""

import pickle
import requests

DECKLIST_JSON_PICKLE = 'decklist_json.pickle'
decklist_json = pickle.loads(open(DECKLIST_JSON_PICKLE, "rb").read())

CARD_JSON_PICKLE = 'card_json.pickle'
card_json = pickle.loads(open(CARD_JSON_PICKLE, "rb").read())

for decklist_id, decklist in decklist_json.items():
    if decklist is None:  # skip deleted decklists
        continue
    
    for card_code, num in decklist['slots'].items():
        if card_code in card_json:
            continue
        
        try:
            response = requests.get('http://arkhamdb.com/api/public/card/{}.json'.format(card_code))
            if response.status_code == 200:
                print(card_code)
                card_json[card_code] = response.json()
        except ConnectionError:
            print('ConnectionError')
            
with open(CARD_JSON_PICKLE, "wb") as cjf:
    cjf.write(pickle.dumps(card_json))