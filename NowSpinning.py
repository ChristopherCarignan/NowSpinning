import requests, json, time, sys, pyaudio, wave, re, matplotlib.pyplot as plt, numpy as np

from PIL import Image
from sys import byteorder
from array import array


'''
Global variables

Some variables that you may (or may not) want to mess with
'''
tmpdir      = '/tmp/'   # temporary directory path (change based on your OS)
aud_dev_id  = 6         # index for "sysdefault" from sounddevice.query_devices() 
thresh      = 512       # threshold for silence/sound; configure based on your system
chunk       = 1024
rec_sec     = 15
sr          = 16000
num_chan    = 1
aud_format  = pyaudio.paInt16
imgdim      = 500
success     = True


'''
API info

You will need to get your own APIs for AudioTag and Last.fm to use the function.
Replace the key variables (at_key, lfm_key) with the keys generated for your APIs.
'''
# API info for AudioTag (https://audiotag.info/apisection)
at_url = 'https://audiotag.info/api'
at_key = 'XXX'

# API info for Last.fm (https://www.last.fm/api)
lfm_url = 'http://ws.audioscrobbler.com/2.0/'
lfm_key = 'XXX'


# Grab your favorite drink and let's start spinning...
def main( ):
    '''
    Created by Christopher Carignan 2020
    
    (this one is just for fun!)

    This function listens constantly on an audio port. If sound is present, 
        the function will begin recording audio in N second intervals, 
        where N is defined by the user (10-20 seconds is recommended).
    The recorded audio is sent to AudioTag for song recognition and the 
        corresponding album art is retrieved from Last.fm. 
    The song info and album art are then displayed as a Matplotlib figure.

    The function is intended for use with a turntable, but can work with any 
        audio source received by the port.
    '''
    
    
    def checkSilence( snd_data ):
        '''
        Check if there is silence on the audio port.
        
        Returns "True" if the audio data is below the user-supplied threshold.
        '''
        return max(snd_data) < thresh
             
        
    def listenAudio( ):
        '''
        Record audio from the audio port, identify it, and
            retrieve and plot the album art along with the song info.
        '''
        while True:
            # create the audio stream for listening
            p = pyaudio.PyAudio()
            stream = p.open(format = aud_format, 
                channels = num_chan, 
                rate = sr,
                input = True, 
                output = True,
                input_device_index = aud_dev_id,
                frames_per_buffer = chunk)

            num_silent = 0
            snd_started = False

            r = array('h')
        
            # little endian, signed short
            snd_data = array('h', stream.read(chunk))
            
            # swap byte read order, if needed
            if byteorder == 'big':
                snd_data.byteswap()
                
            r.extend(snd_data)

            # is sound present?
            silent = checkSilence(snd_data)

            # sound is not present
            if silent and snd_started:
                num_silent += 1
               
            # sound is present
            elif not silent and not snd_started:
                snd_started = True
                
                print('Recording audio...')
                
                frames = []

                # record sample of audio signal
                for i in range(0, int(sr / chunk * rec_sec)):
                    data = stream.read(chunk)
                    frames.append(data)
 
                # save the audio sample
                recordAudio( frames, p )
                
                # identify the audio sample
                song, artist, album, success = songIdent( )

                # check if song is found 
                # (if found, retrieve and display associated album art)
                # (if not found, plot a blank screen)
                if success:
                    print('Song found :)')
                    
                    # retrieve the album art from Last.fm
                    getAlbumArt( artist, album )
                    
                    # display album art along with song/album/artist info
                    displayInfo( song, artist, album )
                    
                    plt.pause(0.001) # 1 ms buffer to release hold
                else:
                    print('Song not found :(')
                    
                    plt.close()
                    plt.style.use('dark_background')
                    plt.rcParams['toolbar'] = 'None'
                    plt.plot()
                    plt.ion()
                    plt.show()
                    plt.axis('off')
                    plt.pause(0.001) # 1 ms buffer to release hold

            # close audio stream to be able to start listening again
            stream.stop_stream()
            stream.close()
            p.terminate()
        
        
    def recordAudio( WriteData, p ):
        '''
        Save audio data frames as a temporary wave file.
        
        Arguments:
        -WriteData: audio data
        -p: pyaudio.PyAudio object
        '''
        wf = wave.open(tmpdir+'audiochunk.wav', 'wb')
        wf.setnchannels(num_chan)
        wf.setsampwidth(p.get_sample_size(aud_format))
        wf.setframerate(sr)
        wf.writeframes(b''.join(WriteData))
        wf.close()


    def songIdent( ):
        '''
        Identify song file using AudioTag.
        '''
        
        print('Identifying song...')
        
        # send request to AudioTag
        payload  = {'action':'identify', 'apikey':at_key}
        
        result 	 = requests.post(
            at_url, data=payload, 
            files={'file':open(tmpdir+'audiochunk.wav', 'rb')}
            )

        # load the JSON response content into a dictionary
        json_object = json.loads(result.text)

        # get token ID associated with the request
        token = json_object['token']

        # send token info to AudioTag for song identification
        payload     = {'action':'get_result', 'token':token, 'apikey':at_key}
        song_result = requests.post(at_url, data=payload)

        # load JSON response content into a dictionary
        song_info = json.loads(song_result.text)

        # check if AudioTag is still analyzing 
        # (if so, wait 1 second and retry, until finished)
        while song_info['result'] == 'wait':
            # wait 1 s
            time.sleep(1)

            # send token info to AudioTag for song identification
            payload     = {'action':'get_result', 'token':token, 'apikey':at_key}
            song_result = requests.post(at_url, data=payload)

            # load JSON response content into a dictionary
            song_info = json.loads(song_result.text)

        # check if song is found (if not found, plot a blank screen)
        if song_info['result'] == 'not found':
            success = False
            song    = []
            artist  = []
            album   = []
        else:
            success = True
            
            # Things get a bit tricky here for 'one-hit wonders'
            # We want to get the original album, not a compilation album
            # So we first need to sift through some of the results from AudioTag
            #   in order to get the earliest recorded version of the song
            allhits = len(song_info['data'])
            years = []
            
            # get the song info for the first selection of matches 
            for hit in range(0,allhits):
                thisHit = song_info['data'][hit]['tracks']
            
                # find the oldest recorded version
                # (i.e. removes reissues, which mess with the Last.fm search)
                albumNums = len(thisHit)
                years.append(hit)
                years[hit] = []
            
                for alb in range(0,albumNums):
                    year = thisHit[alb][-1]
                    years[hit].append(year)
            
            earlyMatch = years.index(min(years))
            firstAlbum = years[earlyMatch].index(min(years[earlyMatch]))

            # extract the song info for the earliest recorded album
            hitInfo = song_info['data'][earlyMatch]['tracks'][firstAlbum]
            
            song   = hitInfo[0]
            artist = hitInfo[1]
            album  = hitInfo[2]

            # remove parenthetical text (i.e. if issue-specific info is included)
            album = re.sub("[\(\[].*?[\)\]]", "", album)

        return song, artist, album, success


    def getAlbumArt( artist, album ):
        '''
        Retrieve album art from Last.fm.

        Arguments:
        -artist = artist name (string)
        -album = album title (string)
        '''
        
        headers = {'user-agent': 'Now Spinning'}
        
        payload = {
            'api_key': lfm_key,
            'method': 'album.getInfo',
            'artist': artist,
            'album': album,
            'format': 'json'
        }

        # send info to Last.fm
        result = requests.get(lfm_url, headers=headers, params=payload)
        
        # check if there is a match (if not, save a blank image)
        if not "error" in result.text:
            # extract the info for the images
            images = result.json()['album']['image']
            
            # extract the URI for the largest (i.e. final listed) image
            image_uri = images[-1]['#text']
            img_data = requests.get(image_uri).content

            # save temporary album art image
            with open(tmpdir+'albumart.jpg', 'wb') as handler:
                handler.write(img_data)
        else:
            # save temporary blank image
            blank = np.zeros([imgdim, imgdim, 3], dtype=np.uint8)
            img_data = Image.fromarray(blank)
            img_data.save(tmpdir+'albumart.jpg')
        

    def displayInfo( song, artist, album ):
        '''
        Display album art from Last.fm along with song info from AudioTag.

        Arguments:
        -song = song title (string)
        -artist = artist name (string)
        -album = album title (string)
        '''
        # clear current figure
        plt.close()

        # create figure with 2 panels
        plt.style.use('dark_background')
        plt.rcParams['toolbar'] = 'None'
        plt.rcParams['font.family'] = 'sans-serif'
        fig, (ax1, ax2) = plt.subplots(1, 2, constrained_layout=True)

        # (resize and) display album art (left panel)
        image = Image.open(tmpdir+'albumart.jpg')
        image.thumbnail([imgdim, imgdim], Image.ANTIALIAS)
        ax1.imshow(image)
        ax1.axis('off')

        # display song, artist, album info (right panel)
        t = 'Song: ' + song + '\n\nArtist: ' + artist + '\n\nAlbum: ' + album
        ax2.text(0.2, 0.2, t, fontsize=18)
        ax2.set_title('Now Spinning', fontsize=24, y=0.8)
        ax2.axis('off')

        # plot the panels!
        plt.ion()
        plt.show()
        plt.pause(0.001) # 1 ms buffer to release hold


    # run the primary function to start listening for sound on the audio port
    # this function will run indefinitely and is a wrapper for all sub-functions
    listenAudio( )
    

if __name__ == "__main__":
    # start with a blank screen
    plt.style.use('dark_background')
    plt.rcParams['toolbar'] = 'None'
    plt.plot()
    plt.ion()
    plt.show()
    plt.axis('off')
    plt.pause(0.001) # 1 ms buffer to release hold
    
    main( )
