import asyncio
import builtins
import hmac
import random
import socket
import uuid
from functools import partial

import blessings

MAX_SHIP_SIZE = 4
NROWS = 10
COLUMNS = 'АБВГДЕЖЗИК'
EMPTY, SHIP, HIT, MISS, DEAD = ' SX/D'

print = partial(builtins.print, flush=True)


def board_hmac(key, message):
    return hmac.new(key.encode(), message.encode()).hexdigest()


def board_display(board, first_player, name):
    x = (not first_player) * term.width // 2
    with term.location(x, 0):
        print(name + ':')
    with term.location(x, 1):
        print('  ' + COLUMNS)
        for i, row in enumerate(board, start=1):
            with term.location(x, i + 1):
                print("{:2d}{}".format(i, ''.join(map(str, row))))


def board_valid(board):
    return True  # XXX check ship placement, their type, etc


def board_to_string(board):
    return ''.join(map(''.join, board))


def board_from_string(s, size=len(COLUMNS)):
    return [s[i:i + size] for i in range(0, len(s), size)]


def index_from_position(position):
    return int(position[1:]) - 1, COLUMNS.index(position[0])


def board_find_damage(board, shot):
    i, j = index_from_position(shot)
    if board[i][j] == EMPTY:
        board[i][j] = MISS
        return board[i][j]

    # hit
    assert board[i][j] in {SHIP, HIT, DEAD}

    # check whether the ship is sunk
    if board[i][j] == DEAD:
        return board[i][j]
    if board[i][j] == HIT:
        return board[i][j]

    # find a ship square to the right, left, up, down
    assert board[i][j] == SHIP
    for direction, stride in enumerate([
            board[i][j + 1:j + MAX_SHIP_SIZE],
            board[i][max(j - MAX_SHIP_SIZE + 1, 0):j][::-1],
            [row[j] for row in board[i + 1:i + MAX_SHIP_SIZE]],
            [row[j] for row in board[max(i - MAX_SHIP_SIZE + 1, 0):i]][::-1]
    ]):
        for square in stride:
            assert square in {SHIP, MISS, EMPTY, HIT}
            if square == SHIP:
                board[i][j] = HIT
                return board[i][j]
            elif square in {EMPTY, MISS}:
                break
    board[i][j] = DEAD
    return board[i][j]


def board_all_dead(board):
    return not any(square == SHIP for row in board for square in row)


def board_mark(board, position, ship):
    assert ship in {SHIP, HIT, MISS, DEAD}
    i, j = index_from_position(position)
    board[i][j] = ship


async def game(recv, send, first_player, name):
    # XXX arrange ships
    if first_player:
        board = [
            # АБВГДЕЖЗИК
            'S         ',  # 1
            '          ',  # 2
            '   S    S ',  # 3
            '          ',  # 4
            '  S       ',  # 5
            '        SS',  # 6
            '          ',  # 7
            'SS SS SSS ',  # 8
            '          ',  # 9
            '  SSS SSSS']  # 10
    else:
        board = [
            # АБВГДЕЖЗИК
            'S  S      ',  # 1
            '          ',  # 2
            '   S    S ',  # 3
            '   S  S   ',  # 4
            '          ',  # 5
            '  SSSS  SS',  # 6
            '          ',  # 7
            '      S   ',  # 8
            '      S   ',  # 9
            '  SSS S SS']  # 10

    board = list(map(list, board))

    # send hmac of the board
    key = str(uuid.uuid1())
    board_string = board_to_string(board)
    if not first_player:
        got_board_hmac = await recv()
    await send(board_hmac(key, board_string))
    if first_player:
        got_board_hmac = await recv()

    # play
    shots = [column + str(row) for row in range(1, NROWS + 1)
             for column in COLUMNS]
    random.shuffle(shots)
    if first_player:
        shot = shots.pop()  # XXX random shot
        await send(shot)
    else:
        shot = None
    enemy_ships_count = 10
    enemy_board = [[None] * len(row) for row in board]
    while True:
        board_display(board, first_player, name)
        answer = await recv()
        assert answer not in {EMPTY, None}
        if shot:  # we've fired a shot
            board_mark(enemy_board, shot, answer)
            if answer in {HIT, DEAD}:
                if answer == DEAD:
                    enemy_ships_count -= 1
                    if enemy_ships_count == 0:  # game over
                        await send(key)  # send key to check our board
                        await send(board_string)
                        break
                shot = shots.pop()  # XXX random shot
                await send(shot)
            elif answer == MISS:
                shot = None
            else:
                assert 0, 'invalid answer'
        elif shot is None:  # we are under attack
            damage = board_find_damage(board, answer)
            await send(damage)
            if damage == MISS:  # our turn
                shot = shots.pop()  # XXX random shot
                await send(shot)
            elif damage == DEAD and board_all_dead(board):  # game over
                key_enemy = await recv()  # get key to check their board
                board_string_enemy = await recv()
                break
            assert damage in {HIT, MISS, DEAD}

    board_display(board, first_player, name)

    # check the board, declare winner
    if enemy_ships_count:  # loser
        got_board = board_from_string(board_string_enemy)
        expected_board_hmac = board_hmac(key_enemy, board_string_enemy)
        lost = (got_board_hmac == expected_board_hmac
                and board_valid(got_board)
                and board_to_string(got_board) == board_string_enemy
                and len(got_board) == len(enemy_board)
                and all(len(row) == len(row_enemy)
                        for row, row_enemy in zip(got_board, enemy_board))
                # check reported damage corresponds to the received board
                and all(((cell == SHIP and cell_enemy in {HIT, DEAD, None})
                         or (cell == EMPTY and cell_enemy in {MISS, None}))
                        for row, row_enemy in zip(got_board, enemy_board)
                        for cell, cell_enemy in zip(row, row_enemy)))
        if lost:
            await send('You won!')
            with term.location(0, term.height - 2):
                print(f'{name} lost.')
        else:
            await send('Your board is wrong. You lost for breaking the rules.')
            with term.location(0, term.height - 2):
                print(f'{name} won. The enemy have broken the rules.')
    else:  # winner
        game_over_message = await recv()
        with term.location(0, term.height - 2):
            print(f'{name} got: {game_over_message}')


def create_recv_send(reader, writer):
    async def send(s):
        return writer.write((s + '\n').encode())
        await writer.drain()

    async def recv():
        data = await reader.readline()
        return data.decode().rstrip('\n')
    return recv, send


async def main():
    global term
    port = int.from_bytes(b'SB', 'big')  # SB stands for Sea Battle
    host = socket.gethostname() + '.local'  # Zeroconf

    async def second_player():
        reader, writer = await asyncio.open_connection(host, port)
        await game(*create_recv_send(reader, writer),
                   first_player=False, name='Боб')
        writer.close()

    async def play_game():
        done = asyncio.Event()

        async def callback(reader, writer):
            await game(*create_recv_send(reader, writer),
                       first_player=True, name='Алиса')
            writer.close()
            done.set()

        server = await asyncio.start_server(callback, host, port)
        await asyncio.wait([done.wait(), second_player()],
                           return_when=asyncio.FIRST_COMPLETED)
        server.close()

        term = blessings.Terminal()
        with term.hidden_cursor(), term.fullscreen():
            print(term.clear(), end='', flush=True)
            await play_game()
            with term.location(0, term.height - 1):
                input('Press <Enter> to exit.')

if __name__ == '__main__':
    asyncio.get_event_loop().run_until_complete(main())
