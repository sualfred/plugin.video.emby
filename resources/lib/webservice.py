# -*- coding: utf-8 -*-

#################################################################################################

import BaseHTTPServer
import logging
import httplib
import threading
import urlparse
import os
import socket
import Queue

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from helper import settings, window, playstrm

#################################################################################################

LOG = logging.getLogger("EMBY."+__name__)
ADDON = xbmcaddon.Addon(id='plugin.video.emby')
PORT = 57578

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
        self.pending = []
        self.threads = []
        self.queue = Queue.Queue()

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

    def handle(self):

        ''' To quiet socket errors with 404.
        '''
        try:
            BaseHTTPServer.BaseHTTPRequestHandler.handle(self)
        except Exception as error:
            pass#xbmc.log(str(error), xbmc.LOGWARNING)

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
        self.handle_request(True)

        return

    def do_GET(self):

        ''' Called on GET requests
        '''
        self.handle_request()

        return

    def handle_request(self, headers_only=False):

        '''Send headers and reponse
        '''
        try:
            #xbmc.log(str(self.path), xbmc.LOGWARNING)

            if 'extrafanart' in self.path or 'extrathumbs' in self.path:
                raise Exception("unsupported artwork request")

            if headers_only:

                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()

            elif 'file.strm' not in self.path:
                self.images()
            else:
                self.strm()

        except Exception as error:
            self.send_error(500, "[ webservice ] Exception occurred: %s" % error)

        xbmc.log("<[ webservice/%s/%s ]" % (str(id(self)), int(not headers_only)), xbmc.LOGWARNING)

        return

    def strm(self):

        ''' Return a dummy video and and queue real items.
        '''
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

        params = self.get_params()
        loading_videos = ['default', 'black']
        loading = xbmc.translatePath(os.path.join(ADDON.getAddonInfo('path'), 'resources', 'skins', 'default', 'media', 'videos', loading_videos[int(settings('loadingVideo') or 0)], 'emby-loading.mp4')).decode('utf-8')
        #xbmc.translatePath("special://home/addons/plugin.video.emby/resources/skins/default/media/videos/%s/emby-loading.mp4" % loading_videos[int(settings('loadingVideo') or 0)]).decode('utf-8')
        self.wfile.write(loading)

        if params['Id'] not in self.server.pending:

            xbmc.log("[ webservice/%s ] path: %s params: %s" % (str(id(self)), str(self.path), str(params)), xbmc.LOGWARNING)
            self.server.pending.append(params['Id'])
            self.server.queue.put((params, ''.join(["http://127.0.0.1", ":", str(PORT), self.path.encode('utf-8')]),))

            if len(self.server.threads) < 1:

                queue = QueuePlay(self.server)
                queue.start()
                self.server.threads.append(queue)

    def images(self):

        ''' Return a dummy image for unwanted images requests over the webservice.
            Required to prevent freezing of widget playback if the file url has no
            local textures cached yet.
        '''
        image = xbmc.translatePath(os.path.join(ADDON.getAddonInfo('path'), 'icon.png')).decode('utf-8')
        #xbmc.translatePath("special://home/addons/plugin.video.emby/icon.png").decode('utf-8')

        self.send_response(200)
        self.send_header('Content-type', 'image/png')
        modified = xbmcvfs.Stat(image).st_mtime()
        self.send_header('Last-Modified', "%s" % modified)
        image = xbmcvfs.File(image)
        size = image.size()
        self.send_header('Content-Length', str(size))
        self.end_headers()

        self.wfile.write(image.readBytes())
        image.close()

class QueuePlay(threading.Thread):

    def __init__(self, server):

        self.server = server
        threading.Thread.__init__(self)

    def run(self):

        ''' Queue up strm playback that was called in the webservice.
            Remove the dummy video in player.py (virtual library paths) and here (actual strm link).

            Required delay for widgets, custom skin containers and non library windows.
            Otherwise Kodi will freeze if no artwork textures are cached yet in Textures13.db
            Will be skipped if the player already has media and is playing.

            Important: Never move the check to start play_folder() to prevent race conditions!
        '''
        LOG.info("-->[ queue play ]")
        count = 0

        while True:

            try:
                params, path = self.server.queue.get(timeout=1)
            except Queue.Empty:

                self.server.threads.remove(self)
                self.server.pending = []
                
                break

            play = playstrm.PlayStrm(params, params.get('ServerId'))
            item_id = params['Id']
            current_position = max(xbmc.PlayList(xbmc.PLAYLIST_VIDEO).getposition(), 0)
            LOG.info("[ queue play/%s/%s ]", item_id, current_position)

            try:
                if self.server.pending.count(item_id) != len(self.server.pending):
                    current_position = play.play_folder(current_position)
                else:
                    while not window('emby_loadingvideo.bool'):

                        if count > 20:
                            raise Exception("Failed to start queue play.")

                        count += 1
                        xbmc.sleep(50)

                        if self.server.pending.count(item_id) != len(self.server.pending):
                            break

                    window('emby_loadingvideo', clear=True)
                    current_window = xbmcgui.getCurrentWindowId()

                    if not current_window == 12005:

                        LOG.info("[ queue play/delay/%s ]", current_window)
                        xbmc.sleep(500)

                    current_position = play.play(params.get('mode') == 'playfolder')

            except Exception as error:

                LOG.error(error)
                xbmc.Player().stop()
                self.server.queue.queue.clear()

                continue

            play.remove_from_playlist_by_path(path)
            self.server.queue.task_done()

        LOG.info("--<[ queue play ]")
