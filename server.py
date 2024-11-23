# server.py
# Backend server using Flask and Socket.IO
import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import random
import threading

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)

rooms = {}  # Stores game room data
sid_to_user = {}  # Maps session IDs to user data

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('create_room')
def on_create_room(data):
    room = data['room']
    username = data['username']
    sid = request.sid
    join_room(room)
    sid_to_user[sid] = {'username': username, 'room': room}
    if room not in rooms:
        rooms[room] = {
            'players': {},
            'numbers_called': [],
            'chat': [],
            'game_started': False,
            'turn_order': [],
            'current_turn': 0,
            'timer': None,
            'start_votes': set(),
            'waiting_for_players': True
        }
    rooms[room]['players'][username] = {
        'board': [],
        'marked': [],
        'bingo': False,
        'submitted': False
    }
    emit('room_created', {'room': room})
    update_player_list(room)

@socketio.on('join_room')
def on_join_room(data):
    room = data['room']
    username = data['username']
    sid = request.sid
    join_room(room)
    sid_to_user[sid] = {'username': username, 'room': room}
    if room not in rooms:
        emit('error', {'message': '房間不存在'})
        return
    rooms[room]['players'][username] = {
        'board': [],
        'marked': [],
        'bingo': False,
        'submitted': False
    }
    emit('player_joined', {'username': username}, room=room)
    update_player_list(room)

@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    user = sid_to_user.get(sid)
    if user:
        room = user['room']
        username = user['username']
        leave_room(room)
        del sid_to_user[sid]
        if room in rooms and username in rooms[room]['players']:
            del rooms[room]['players'][username]
            if len(rooms[room]['players']) == 0:
                del rooms[room]
            else:
                update_player_list(room)
                # Handle game state if a player leaves during the game
                if rooms[room]['game_started']:
                    if username in rooms[room]['turn_order']:
                        idx = rooms[room]['turn_order'].index(username)
                        del rooms[room]['turn_order'][idx]
                        if idx <= rooms[room]['current_turn']:
                            rooms[room]['current_turn'] -= 1
                    if len(rooms[room]['turn_order']) < 2:
                        # End game if less than two players
                        rooms[room]['game_started'] = False
                        emit('game_ended', {'message': '遊戲因玩家離開而結束'}, room=room)
                    else:
                        emit('player_left', {'username': username}, room=room)

def update_player_list(room):
    players = list(rooms[room]['players'].keys())
    emit('update_player_list', {'players': players}, room=room)

@socketio.on('submit_board')
def on_submit_board(data):
    sid = request.sid
    user = sid_to_user.get(sid)
    if not user:
        return
    room = user['room']
    username = user['username']
    board = data['board']  # List of 25 numbers
    rooms[room]['players'][username]['board'] = board
    rooms[room]['players'][username]['marked'] = [False]*25
    rooms[room]['players'][username]['submitted'] = True
    emit('board_submitted', {'username': username}, room=room)
    # Send updated submission status to all players
    submission_status = {uname: player['submitted'] for uname, player in rooms[room]['players'].items()}
    emit('update_submission_status', {'submission_status': submission_status}, room=room)

@socketio.on('start_game')
def on_start_game():
    sid = request.sid
    user = sid_to_user.get(sid)
    if not user:
        return
    room = user['room']
    username = user['username']
    rooms[room]['start_votes'].add(username)
    # Check if game can start
    if len(rooms[room]['players']) >= 2 and len(rooms[room]['start_votes']) >= 2:
        all_submitted = all(p['submitted'] for p in rooms[room]['players'].values())
        if all_submitted:
            rooms[room]['game_started'] = True
            rooms[room]['waiting_for_players'] = False
            # Randomize turn order
            rooms[room]['turn_order'] = list(rooms[room]['players'].keys())
            random.shuffle(rooms[room]['turn_order'])
            rooms[room]['current_turn'] = 0
            emit('game_started', {'turn_order': rooms[room]['turn_order']}, room=room)
            start_turn_timer(room)
        else:
            emit('waiting_for_players', {'message': '等待其他玩家提交板'}, room=room)
    else:
        emit('waiting_for_players', {'message': '需要至少兩名玩家開始遊戲'}, room=room)

def start_turn_timer(room):
    # Cancel previous timer
    if rooms[room]['timer']:
        rooms[room]['timer'].cancel()
    # Start new timer
    timer = threading.Timer(15, skip_turn, args=[room])
    rooms[room]['timer'] = timer
    timer.start()
    # Notify all players whose turn it is
    current_player = rooms[room]['turn_order'][rooms[room]['current_turn']]
    emit('your_turn', {'username': current_player}, room=room)

def skip_turn(room):
    # Handle player timeout
    current_player = rooms[room]['turn_order'][rooms[room]['current_turn']]
    emit('turn_skipped', {'username': current_player}, room=room)
    advance_turn(room)

def advance_turn(room):
    rooms[room]['current_turn'] = (rooms[room]['current_turn'] + 1) % len(rooms[room]['turn_order'])
    start_turn_timer(room)

@socketio.on('number_selected')
def on_number_selected(data):
    sid = request.sid
    user = sid_to_user.get(sid)
    if not user:
        return
    room = user['room']
    username = user['username']
    number = data['number']
    # Check if it's the player's turn
    current_player = rooms[room]['turn_order'][rooms[room]['current_turn']]
    if username != current_player:
        emit('error', {'message': '不是你的回合'})
        return
    # Check if number has already been called
    if number in rooms[room]['numbers_called']:
        emit('error', {'message': '該數字已被選過'})
        return
    rooms[room]['numbers_called'].append(number)
    # Update all players' marked numbers
    winner = None
    for uname, player in rooms[room]['players'].items():
        if number in player['board']:
            index = player['board'].index(number)
            player['marked'][index] = True
            # Check for BINGO
            if check_bingo(player['marked']):
                player['bingo'] = True
                winner = uname
    emit('number_called', {
        'number': number,
        'winner': winner,
        'username': username,
        'numbers_called': rooms[room]['numbers_called']
    }, room=room)
    if winner:
        rooms[room]['game_started'] = False
        if rooms[room]['timer']:
            rooms[room]['timer'].cancel()
        emit('game_over', {'winner': winner}, room=room)
    else:
        advance_turn(room)

@socketio.on('send_message')
def on_send_message(data):
    sid = request.sid
    message = data['message']
    user = sid_to_user.get(sid)
    if user:
        username = user['username']
        room = user['room']
    else:
        username = '匿名流言'
        room = None  # Broadcast to all
    if room:
        emit('new_message', {'username': username, 'message': message}, room=room)
    else:
        emit('new_message', {'username': username, 'message': message})

@socketio.on('restart_game')
def on_restart_game():
    sid = request.sid
    user = sid_to_user.get(sid)
    if not user:
        return
    room = user['room']
    if room not in rooms:
        emit('error', {'message': '房間不存在'})
        return
    # Reset game state
    rooms[room]['game_started'] = False
    rooms[room]['numbers_called'] = []
    rooms[room]['turn_order'] = []
    rooms[room]['current_turn'] = 0
    rooms[room]['start_votes'] = set()
    rooms[room]['waiting_for_players'] = True
    for player in rooms[room]['players'].values():
        player['board'] = []
        player['marked'] = []
        player['bingo'] = False
        player['submitted'] = False
    # Notify all players to reset their boards
    emit('restart_game', room=room)

def check_bingo(marked):
    lines = [
        [0,1,2,3,4],
        [5,6,7,8,9],
        [10,11,12,13,14],
        [15,16,17,18,19],
        [20,21,22,23,24],
        [0,5,10,15,20],
        [1,6,11,16,21],
        [2,7,12,17,22],
        [3,8,13,18,23],
        [4,9,14,19,24],
        [0,6,12,18,24],
        [4,8,12,16,20]
    ]
    for line in lines:
        if all([marked[i] for i in line]):
            return True
    return False

# if __name__ == '__main__':
#     socketio.run(app, debug=True)
if __name__ == '__main__':
    import os
    # Render 会通过环境变量 PORT 指定动态端口
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)