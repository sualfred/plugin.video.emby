# -*- coding: utf-8 -*-

#################################################################################################

import logging

import xbmc
import xbmcgui
import xbmcvfs

import api
import playutils
from . import _, settings, dialog, window, JSONRPC
from objects import Actions
from emby import Emby

#################################################################################################

LOG = logging.getLogger("EMBY."+__name__)

#################################################################################################


class PlayStrm(object):

    def __init__(self, params, server_id=None):

        ''' Workflow: Strm that calls our webservice in database. When played,
            the webserivce returns a dummy file to play. Meanwhile,
            PlayStrm adds the real listitems for items to play to the playlist.
        '''
        LOG.info(">[ play strm ]")
        self.info = {
            'Intros': None,
            'Item': None,
            'Id': params.get('Id'),
            'DbId': params.get('KodiId'),
            'Transcode': params.get('Transcode') or settings('playFromTranscode.bool') or None,
            'AdditionalParts': None,
            'ServerId': server_id,
            'KodiPlaylist': xbmc.PlayList(xbmc.PLAYLIST_VIDEO),
            'Server': Emby(server_id).get_client()
        }
        self.actions = Actions(server_id, self.info['Server']['auth/server-address'])
        self.set_listitem = self.actions.set_listitem
        self.params = params
        self._detect_play()
        LOG.info("<[ play strm ]")

    def remove_from_playlist(self, index, playlist_id=None):

        playlist = playlist_id or 1
        JSONRPC('Playlist.Remove').execute({'playlistid': playlist_id, 'position': index})

    def _get_intros(self):
        self.info['Intros'] = self.info['Server']['api'].get_intros(self.info['Id'])

    def _get_additional_parts(self):
        self.info['AdditionalParts'] = self.info['Server']['api'].get_additional_parts(self.info['Id'])

    def _get_item(self):
        self.info['Item'] = self.info['Server']['api'].get_item(self.info['Id'])

    def _detect_play(self):

        ''' Download all information needed to build the playlist for item requested.
        '''
        if self.info['Id']:

            self._get_intros()
            self._get_item()
            self._get_additional_parts()

    def play(self, play_folder=False):

        ''' Create and add listitems to the Kodi playlist.
        '''
        clear_playlist = self.actions.detect_playlist(self.info['Item'])

        items = JSONRPC('Playlist.GetItems').execute({'playlistid': 1})

        for index, item in enumerate(reversed(items['result']['items'])):

            if item['label'] == 'emby-loading.mp4':
    
                playlist_index = len(items['result']['items']) - index
                LOG.info("removing: %s", playlist_index)
                self.remove_from_playlist(playlist_index)

        self.actions.verify_playlist()


        if play_folder:

            LOG.info("[ play folder ]")
            clear_playlist = False
            #self.info['StartIndex'] = max(self.info['KodiPlaylist'].getposition(), 0) 
            #self.info['Index'] = self.info['StartIndex'] + 1
        else:
            LOG.info("[ play ]")

        self.info['StartIndex'] = max(self.info['KodiPlaylist'].getposition(), 0)
        self.info['Index'] = self.info['StartIndex'] + 1

        if clear_playlist or window('emby_playinit') == 'widget':

            window('emby_playinit', "widget")
            self.actions.get_playlist(self.info['Item']).clear()
            clear_playlist = True

        listitem = xbmcgui.ListItem()
        #self.info['Index'] = self.info['StartIndex'] + 1
        LOG.info("[ index/%s ]", self.info['Index'])
        self._set_playlist(listitem)

        if clear_playlist:
            LOG.info("[ forced play ]")
            xbmc.Player().play(self.info['KodiPlaylist'], startpos=self.info['StartIndex'], windowed=False)
        else:
            xbmc.Player().playnext()

        #self.remove_from_playlist(self.info['StartIndex'])

        items = JSONRPC('Playlist.GetItems').execute({'playlistid': 1})

        for index, item in enumerate(reversed(items['result']['items'])):

            if item['label'] == 'emby-loading.mp4':
    
                playlist_index = len(items['result']['items']) - index - 1
                LOG.info("removing: %s", playlist_index)
                self.remove_from_playlist(playlist_index)
                self.info['KodiPlaylist'].remove('emby-loading.mp4')

        self.actions.verify_playlist()


        return self.info['Index']

    def play_folder(self, position=None):
        
        LOG.info("[ play folder ]")
        window('emby_playinit', "playfolder")

        listitem = xbmcgui.ListItem()
        self.info['StartIndex'] = position or max(self.info['KodiPlaylist'].size(), 0)
        self.info['Index'] = self.info['StartIndex'] + 1
        LOG.info(self.info['Index'])

        self.actions.set_listitem(self.info['Item'], listitem, self.info['DbId'])
        url = "http://127.0.0.1:57578/emby/play/file.strm?Id=%s&mode=playfolder" % self.info['Id']
        listitem.setPath(url)
        self.info['KodiPlaylist'].add(url=url, listitem=listitem, index=self.info['Index'])

        LOG.info("<[ play folder ]")

        return self.info['Index']

    def _set_playlist(self, listitem):

        ''' Verify seektime, set intros, set main item and set additional parts.
            Detect the seektime for video type content.
            Verify the default video action set in Kodi for accurate resume behavior.
        '''
        seektime = window('emby.resume')

        if seektime == 'true':
            seektime = True
        elif seektime == 'false':
            seektime = False
        else:
            seektime = None

        window('emby.resume', clear=True)

        if seektime is None and self.info['Item']['MediaType'] in ('Video', 'Audio'):
            resume = self.info['Item']['UserData'].get('PlaybackPositionTicks')

            if resume:
                choice = self.actions.resume_dialog(api.API(self.info['Item'], self.info['Server']).adjust_resume((resume or 0) / 10000000.0), self.info['Item'])

                if choice is None:
                    raise Exception("User backed out of resume dialog.")

                seektime = False if not choice else True

        if settings('enableCinema.bool') and not seektime:
            self._set_intros()

        play = playutils.PlayUtilsStrm(self.info['Item'], self.info['Transcode'], self.info['ServerId'], self.info['Server'])
        source = play.select_source(play.get_sources())

        if not source:
            raise Exception("Playback selection cancelled")

        play.set_external_subs(source, listitem)
        self.set_listitem(self.info['Item'], listitem, self.info['DbId'], seektime)
        listitem.setPath(self.info['Item']['PlaybackInfo']['Path'])
        playutils.set_properties(self.info['Item'], self.info['Item']['PlaybackInfo']['Method'], self.info['ServerId'])

        self.info['KodiPlaylist'].add(url=self.info['Item']['PlaybackInfo']['Path'], listitem=listitem, index=self.info['Index'])
        self.info['Index'] += 1

        if self.info['Item'].get('PartCount'):
            self._set_additional_parts()

    def _set_intros(self):

        ''' if we have any play them when the movie/show is not being resumed.
        '''
        if self.info['Intros']['Items']:
            enabled = True

            if settings('askCinema') == "true":

                resp = dialog("yesno", heading="{emby}", line1=_(33016))
                if not resp:

                    enabled = False
                    LOG.info("Skip trailers.")

            #elif int(self.info['KodiPlaylist'].getposition()) > 0 and self.info['Item']['Type'] == 'Episode':
            #    enabled = False

            if enabled:
                for intro in self.info['Intros']['Items']:

                    listitem = xbmcgui.ListItem()
                    LOG.info("[ intro/%s ] %s", intro['Id'], intro['Name'])

                    play = playutils.PlayUtilsStrm(intro, False, self.info['ServerId'], self.info['Server'])
                    source = play.select_source(play.get_sources())
                    self.set_listitem(intro, listitem, intro=True)
                    listitem.setPath(intro['PlaybackInfo']['Path'])
                    playutils.set_properties(intro, intro['PlaybackInfo']['Method'], self.info['ServerId'])

                    self.info['KodiPlaylist'].add(url=intro['PlaybackInfo']['Path'], listitem=listitem, index=self.info['Index'])
                    self.info['Index'] += 1

                    window('emby.skip.%s' % intro['Id'], value="true")

    def _set_additional_parts(self, item_id):

        ''' Create listitems and add them to the stack of playlist.
        '''
        for part in self.info['AdditionalParts']['Items']:

            listitem = xbmcgui.ListItem()
            LOG.info("[ part/%s ] %s", part['Id'], part['Name'])

            play = playutils.PlayUtilsStrm(part, self.info['Transcode'], self.info['ServerId'], self.info['Server'])
            source = play.select_source(play.get_sources())
            play.set_external_subs(source, listitem)
            self.set_listitem(part, listitem)
            listitem.setPath(part['PlaybackInfo']['Path'])
            playutils.set_properties(part, part['PlaybackInfo']['Method'], self.info['ServerId'])

            self.info['KodiPlaylist'].add(url=part['PlaybackInfo']['Path'], listitem=listitem, index=self.info['Index'])
            self.info['Index'] += 1
