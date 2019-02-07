# -*- coding: utf-8 -*-

#################################################################################################

import BaseHTTPServer
import logging
import httplib
import threading
import urlparse
import os

import xbmc
import xbmcaddon
import xbmcgui

from helper import playstrm

#################################################################################################

ADDON = xbmcaddon.Addon(id='plugin.video.emby')
PORT = 57578
LOG = logging.getLogger("EMBY."+__name__)

#################################################################################################

class WebService(threading.Thread):

    ''' Run a webservice to trigger playback.
    '''
    def __init__(self):
        threading.Thread.__init__(self)

    def stop(self):

        ''' Called when the thread needs to stop
        '''
        try:
            conn = httplib.HTTPConnection("127.0.0.1:%d" % PORT)
            conn.request("QUIT", "/")
            conn.getresponse()
        except Exception as error:
            pass

    def run(self):

        ''' Called to start the webservice.
        '''
        LOG.info("--->[ webservice/%s ]", PORT)

        try:
            server = HttpServer(('127.0.0.1', PORT), requestHandler)
            server.serve_forever()
        except Exception as error:

            if '10053' not in error: # ignore host diconnected errors
                LOG.exception(error)

        LOG.info("---<[ webservice ]")


class HttpServer(BaseHTTPServer.HTTPServer):

    ''' Http server that reacts to self.stop flag.
    '''
    def serve_forever(self):

        ''' Handle one request at a time until stopped.
        '''
        self.stop = False
        self.play = False
        self.queue = []
        self.lock = threading.Lock()

        while not self.stop:
            self.handle_request()



class requestHandler(BaseHTTPServer.BaseHTTPRequestHandler):

    ''' Http request handler. Do not use LOG here,
        it will hang requests in Kodi > show information dialog.
    '''

    def log_message(self, format, *args):

        ''' Mute the webservice requests.
        '''
        pass

    def do_QUIT(self):

        ''' send 200 OK response, and set server.stop to True
        '''
        self.send_response(200)
        self.end_headers()
        self.server.stop = True

    def get_params(self):

        ''' Get the params
        '''
        try:
            path = self.path[1:]

            if '?' in path:
                path = path.split('?', 1)[1]

            params = dict(urlparse.parse_qsl(path))
        except Exception:
            params = {}

        return params

    def do_HEAD(self):

        ''' Called on HEAD requests
        '''
        self.send_response(200)
        self.end_headers()

        return

    def do_GET(self):

        ''' Return plugin path
        '''
        try:
            params = self.get_params()

            if 'file-poster.jpg' in self.path:
                xbmc.log("hello file-poster.jpg", xbmc.LOGWARNING)

            if not params or params.get('Id') is None or 'file.strm' not in self.path:
                raise IndexError("Incomplete URL format")

            if 'extrafanart' in params['Id']:
                raise IndexError("Incorrect Id format %s" % params['Id'])

            xbmc.log("[ webservice ] path: %s params: %s" % (str(self.path), str(params)), xbmc.LOGWARNING)

            self.send_response(200)
            self.send_header('Content-type','text/html')
            self.end_headers()

            play = playstrm.PlayStrm(params, params.get('ServerId'))
            self.wfile.write(xbmc.translatePath(os.path.join(ADDON.getAddonInfo('path'), 'resources', 'lib', 'helper', 'loading.mp4')).decode('utf-8'))

            self.server.queue.append(params['Id'])
            QueuePlay(self.server, self.server.lock, play, params['Id']).start()

        except IndexError as error:

            xbmc.log(str(error), xbmc.LOGWARNING)
            self.send_error(404, "Exception occurred: %s" % error)

        except Exception as error:

            xbmc.log(str(error), xbmc.LOGWARNING)
            self.send_error(500, "Exception occurred: %s" % error)

        return

class QueuePlay(threading.Thread):

    def __init__(self, server, lock, playstrm, item_id):

        self.item_id = item_id
        self.server = server
        self.lock = lock
        self.playstrm = playstrm
        threading.Thread.__init__(self)

    def run(self):

        count = 0

        with self.lock:

            if self.item_id not in self.server.queue:
                return

            player = xbmc.Player()

            try:
                current_file = player.getPlayingFile()
            except Exception:

                while count < 5:
                    try:
                        current_file = player.getPlayingFile()
                        count = 0

                        break
                    except Exception:
                        count += 1

                    if xbmc.sleep(200):
                        return
                else:
                    return

            if current_file.endswith('loading.mp4'):

                try:
                    self.playstrm.play()
                except Exception as error:
                    player.stop()

                while self.item_id in self.server.queue:
                    self.server.queue.remove(self.item_id)
