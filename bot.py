#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Simple Bot to reply to Telegram messages
# This program is dedicated to the public domain under the CC0 license.
"""
This Bot uses the Updater class to handle the bot.
First, a few handler functions are defined. Then, those functions are passed to
the Dispatcher and registered at their respective places.
Then, the bot is started and runs until we press Ctrl-C on the command line.
Usage:
Basic Echobot example, repeats messages.
Press Ctrl-C on the command line or send a signal to the process to stop the
bot.
"""

import os
import logging
import random
import datetime
import psycopg2
import urlparse
import telegram

from decouple import config
from boto3.session import Session
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, InlineQueryHandler, Job

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

logger = logging.getLogger(__name__)

# AWS configuration
AWS_ACCESS_KEY_ID=config('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY=config('AWS_SECRET_ACCESS_KEY')
AWS_STORAGE_BUCKET_NAME=config('AWS_STORAGE_BUCKET_NAME')

# Connect to the database
DATABASE_URL=config('DATABASE_URL')

TELEGRAM_TOKEN = config('TELEGRAM_TOKEN')

session = Session(aws_access_key_id=AWS_ACCESS_KEY_ID,
                  aws_secret_access_key=AWS_SECRET_ACCESS_KEY)
s3 = session.resource('s3')
s3_bucket = s3.Bucket(AWS_STORAGE_BUCKET_NAME)
meme_list = list(s3_bucket.objects.all())


alertFlag = {}


urlparse.uses_netloc.append("postgres")
url = urlparse.urlparse(DATABASE_URL)

conn = psycopg2.connect(
    database=url.path[1:],
    user=url.username,
    password=url.password,
    host=url.hostname,
    port=url.port
)

cur = conn.cursor()

# Command handlers
# To start a bot
def start(bot, update):
    #update.message.reply_text("""Hi! I'm a GotMeme bot. I am the fire that burns against the cold. \nCheck out /help for all available commands now.\nI'm still under development. Stay tuned!""")


    update.message.reply_text(text='<b>bold</b> <i>italic</i> <a href="http://google.com">link</a>.',
                              parse_mode=telegram.ParseMode.HTML)

# Helper function
def help(bot, update):
    #update.message.reply_text("""/start: to start the bot\n/gotmeme: to get a random Games Of Trone meme \n/comment: to send a comment to the developer.\n"""
    #                          """/dailyalerton: once turn on, I will send you a random cat photo daily. \n/dailyalertoff: stop pushing cat photo daily if previously turned on.\nAll other messages: I will respond in the future! \nFor all questions please contact dev @mlusaaa""")
    update.message.reply_text(
        """/start: to start the bot\n/gotmeme: to get a random Games Of Throne meme \n/comment: to send a comment to the developer.\n"""
        """\nFor all questions please contact dev @the_bas""")


# For users to manually retrieve a meme
def gotmeme(bot, update):
    #print ">>> gotmeme"
    rint = random.randint(0,len(meme_list)-1)

    random_meme=meme_list[rint]
    #print random_meme
    meme_https_url = 'https://{host}/{bucket}/{key}'.format(
        host='s3.eu-central-1.amazonaws.com',
        bucket=AWS_STORAGE_BUCKET_NAME,
        key=random_meme.key)
    #print meme_https_url

    update.message.reply_photo(meme_https_url)

# daily update of a cat pic
def dailyalerton(bot, update, job_queue, chat_data):
    user = update.message.from_user
    user_chat_id = update.message.chat_id
    
    # Check to see if daily alert has already been turned on (before cycling)
    if user_chat_id in alertFlag:
        if alertFlag[user_chat_id] == 'Y':
            update.message.reply_text('You have already turned on daily alert. There is no need to turn it on AGAIN.\n'
                                  'Reply /DailyAlertOff to turn daily photo push off, or /help to check out all other command.')
            logger.info(" %s, ID %s attempts to turn on daily alert again while there is already a record on file. (BC)" % (user.first_name, user_chat_id))
            bot.send_message(chat_id='112839673', text="%s, ID %s attempts to turn on daily alert again while there is already a record on file." % (user.first_name, user_chat_id))
            return
    
    # Check to see if daily alert has already been turned on (after cycling)
    cur.execute("SELECT * FROM pushid;")
    if cur.rowcount > 0:
        result = cur.fetchall()
        ids = list(zip(*result)[0])
        if str(user_chat_id) in ids:
            update.message.reply_text('You have already turned on daily alert. There is no need to turn it on AGAIN.\n'
                                      'Reply /DailyAlertOff to turn daily photo push off, or /help to check out all other command.')
            logger.info(" %s, ID %s attempts to turn on daily alert again while there is already a record on file. (AC)" % (user.first_name, user_chat_id))
            bot.send_message(chat_id='112839673', text="%s, ID %s attempts to turn on daily alert again while there is already a record on file." % (user.first_name, user_chat_id))
            job = job_queue.run_daily(scheduleCat, datetime.datetime.now(), context=user_chat_id)
            chat_data['job'] = job
            return
        
    # if not then proceed
    update.message.reply_text('Daily alert turns ON. I will send you a cat photo every 24 hours.\n'
                              'Reply /DailyAlertOff to turn daily photo push off, or /help to check out all other command.')
    logger.info("Daily alert turned ON for %s, ID %s" % (user.first_name, user_chat_id))
    bot.send_message(chat_id='112839673', text="Daily alert turned ON for %s, ID %s" % (user.first_name, user_chat_id))
    alertFlag[user_chat_id]='Y'
    
    # Update the database
    cur.execute("INSERT INTO pushid (id,status,eff_date) VALUES (%s, %s, %s);", (user_chat_id, 'Y',datetime.datetime.now()))
    conn.commit()
    
    # Add job to queue
    job = job_queue.run_daily(scheduleCat, datetime.datetime.now(), context=user_chat_id)
    chat_data['job'] = job
    
# Turn off daily update of a cat pic    
def dailyalertoff(bot, update, chat_data):
    user = update.message.from_user
    user_chat_id = update.message.chat_id
    
    #Removes the job if the user changed their mind
    if 'job' not in chat_data:
        update.message.reply_text("You don't have daily alert turn on!")
        return
    job = chat_data['job']
    job.schedule_removal()
    del chat_data['job']
    
    update.message.reply_text('Daily alert turns OFF. No cat photo will be auto pushed.\n'
                              'Reply /DailyAlertOn to turn daily photo push on, or /help to check out all other command.')
    logger.info("Daily alert turned OFF for %s, ID %s" % (user.first_name, user_chat_id))
    bot.send_message(chat_id='112839673', text="Daily alert turned OFF for %s, ID %s" % (user.first_name, user_chat_id))
    alertFlag[user_chat_id]='N'
    
    # Update the database
    cur.execute("""DELETE FROM pushid WHERE id = %s AND status = 'Y';""", (str(user_chat_id),))
    conn.commit()
    
# The function to be called when daily cat alert is on    
def scheduleCat(bot, job):
    rint = random.randint(0,len(meme_list)-1)
    bot.send_photo(job.context, photo=meme_list.ix[rint][1])

# Feedback to the dev    
def comment(bot, update, args):
    txt = ' '.join(args)
    if len(txt) == 0:
        update.message.reply_text("""ERROR!! No input was received.""")
    else:
        update.message.reply_text("""Thanks for your feedback! I'll take it :)""")
        newinfo = "New feedback received! From: "+update.message.from_user.username+", Content: "+txt
        bot.send_message(chat_id='112839673', text=newinfo)

# Log all errors
def error(bot, update, error):
    logger.warn('Update "%s" caused error "%s"' % (update, error))

# Handles all unknown commands   
def unknown(bot, update):
    bot.send_message(chat_id=update.message.chat_id, text="ERROR!! Sorry, I didn't understand that command. Please try again!")

# Inline handling - under devlopment
#def inlinequery(bot, update):
#    query = update.inline_query.query
##    results = list()
##
##    results.append(InlineQueryResultArticle(id=uuid4(),
##                                            title="Caps",
##                                            input_message_content=InputTextMessageContent(
##                                                query.upper())))
#
#    #update.inline_query.answer(results)
#    update.inline_query.answer(InlineQueryResultArticle(id=uuid4(),title="Caps",input_message_content=InputTextMessageContent(query.upper())))
#    #update.message.reply_photo("https://drive.google.com/file/d/0BylaRC6E32UxcVZfYjAxWTRpZ3M/view?usp=sharing")

def main():
    print "Telegram GotMEME bot is running..."

    # Create the EventHandler and pass it your bot's token.
    updater = Updater(TELEGRAM_TOKEN)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # on different commands - answer in Telegram
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help))
    dp.add_handler(CommandHandler('GoTMeme', gotmeme))
    dp.add_handler(CommandHandler('Comment', comment, pass_args=True))
    #dp.add_handler(CommandHandler('DailyAlertOn',dailyalerton, pass_job_queue=True,
    #                              pass_chat_data=True))
    #dp.add_handler(CommandHandler('DailyAlertOff',dailyalertoff,pass_chat_data=True))

    # on noncommand i.e message
    dp.add_handler(MessageHandler(Filters.command, unknown))
    
    # Inline query handling
#    dp.add_handler(InlineQueryHandler(inlinequery))

    # log all errors
    dp.add_error_handler(error)

    # Start the Bot
    #updater.start_polling(poll_interval = 1.0,timeout=20)
    PORT = int(os.environ.get('PORT'))
    updater.start_webhook(listen="0.0.0.0",
                          port=PORT,
                          url_path=TELEGRAM_TOKEN)
    updater.bot.setWebhook("https://got-meme-bot.herokuapp.com/" + TELEGRAM_TOKEN)

    # Run the bot until you press Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()
    
    # Close communication with the database
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()