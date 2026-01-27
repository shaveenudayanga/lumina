from pathlib import Path
p=Path('lumina_unified.py')
s=p.read_text()
start_token='\ndef stop(self):'
end_token='\n\n# ============== MAIN APPLICATION =============='
si=s.find(start_token)
ei=s.find(end_token)
if si==-1 or ei==-1:
    print('Could not find stop() block boundaries', si, ei)
else:
    before=s[:si]
    after=s[ei:]
    new_block=('\n    def stop(self):\n'
               '        """Stop the live conversation and notify ESP32 to stop audio streaming."""\n'
               '        self.running = False\n'
               '        # Send stop command to ESP32\n'
               '        if self.robot:\n'
               '            try:\n'
               '                self.robot.send_command("AUDIO_STOP")\n'
               '            except Exception:\n'
               '                pass\n\n'
               '    def cleanup(self):\n'
               '        """Cleanup resources after a live conversation ends."""\n'
               '        self.running = False\n'
               '        # Ensure ESP32 stops streaming\n'
               '        if self.robot:\n'
               '            try:\n'
               '                self.robot.send_command("AUDIO_STOP")\n'
               '            except Exception:\n'
               '                pass\n'
               '        # Close UDP sockets\n'
               '        try:\n'
               '            self.audio_in_socket.close()\n'
               '        except Exception:\n'
               '            pass\n'
               '        try:\n'
               '            self.audio_out_socket.close()\n'
               '        except Exception:\n'
               '            pass\n'
               '        print("\\n💬 Live conversation ended")\n\n')
    s2=before+new_block+after
    p.write_text(s2)
    print('Patched stop/cleanup block successfully')
