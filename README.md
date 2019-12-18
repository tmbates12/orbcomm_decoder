# orbcomm_decoder
Demodulate and decode the 4800bps SDPSK ORBCOMM downlink from FM audio

orbcomm_recv.grc is a GNU Radio flowgraph meant to take the NFM demodulated signal from an SDR, 
most convienently through a Virtual Audio Cable.

orbcomm.py inputs symbols from the GNU Radio flowgraph over UDP, default port 10000 and then
outputs the decoded packet content to stdout.
