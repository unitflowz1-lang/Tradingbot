import MetaTrader5 as mt5
import sys

if not mt5.initialize():
    print("initialize() failed")
    quit()

tickets = [55302996914, 55303028242]

for ticket in tickets:
    deals = mt5.history_deals_get(position=ticket)
    if deals:
        print(f"\nDeals for position {ticket}:")
        for deal in deals:
            print(f"Deal type: {deal.type}, Entry: {deal.entry}, Reason: {deal.reason}, Comment: {deal.comment}, Price: {deal.price}")
    else:
        print(f"\nNo deals found for position {ticket}. It might still be open.")

mt5.shutdown()
