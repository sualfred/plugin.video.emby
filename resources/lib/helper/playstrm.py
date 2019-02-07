# -*- coding: utf-8 -*-

#################################################################################################

import xbmc
import xbmcgui
import xbmcvfs

import api
import playutils
from . import _, settings, window, JSONRPC
from objects import Actions
from emby import Emby

#################################################################################################


class PlayStrm(object):

    def __init__(self, params, server_id=None):

        ''' Workflow: Strm that calls our webservice in database. When played,
            the webserivce returns a dummy file to play. Meanwhile, 
            PlayStrm adds the real listitems for items to play to the playlist.
        '''
        xbmc.log("[ play strm ]", xbmc.LOGWARNING)
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

    def skip_placeholder(self):

        xbmc.Player().playnext()
        JSONRPC('Playlist.Remove').execute({'playlistid': 1, 'position': self.info['StartIndex']})

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

    def play(self):

        ''' Create and add listitems to the Kodi playlist.
        '''
        clear_playlist = self.actions.detect_playlist(self.info['Item'])

        listitem = xbmcgui.ListItem()
        self.info['StartIndex'] = max(self.info['KodiPlaylist'].getposition(), 0)
        self.info['Index'] = self.info['StartIndex'] + 1

        self._set_playlist(listitem)

        if clear_playlist:
            xbmc.log("hello world -- clearing", xbmc.LOGWARNING)
            xbmc.Player().play(self.info['KodiPlaylist'], startpos=self.info['StartIndex'] + 1, windowed=False)
            JSONRPC('Playlist.Remove').execute({'playlistid': 1, 'position': self.info['StartIndex'] + 1})
        else:
            self.skip_placeholder()

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
                    xbmc.log("Skip trailers.", xbmc.LOGWARNING)

            if enabled:
                for intro in self.info['Intros']['Items']:

                    listitem = xbmcgui.ListItem()
                    xbmc.log("[ intro/%s ] %s" % (intro['Id'], intro['Name']), xbmc.LOGWARNING)

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
            xbmc.log("[ part/%s ] %s" % (part['Id'], part['Name']), xbmc.LOGWARNING)

            play = playutils.PlayUtilsStrm(part, self.info['Transcode'], self.info['ServerId'], self.info['Server'])
            source = play.select_source(play.get_sources())
            play.set_external_subs(source, listitem)
            self.set_listitem(part, listitem)
            listitem.setPath(part['PlaybackInfo']['Path'])
            playutils.set_properties(part, part['PlaybackInfo']['Method'], self.info['ServerId'])

            self.info['KodiPlaylist'].add(url=part['PlaybackInfo']['Path'], listitem=listitem, index=self.info['Index'])
            self.info['Index'] += 1
