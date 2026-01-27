from pathlib import Path
p=Path('lumina_unified.py')
s=p.read_text()
start_token='    def stop(self):'
end_token='\n\n# ============== MAIN APPLICATION =============='
si=s.find(start_token)
ei=s.find(end_token)
if si==-1 or ei==-1:
    print('Could not find stop() block boundaries', si, ei)
else:
    before=s[:si]
    after=s[ei:]
    new_block='''
    def stop(self):
        """Stop the live conversation and notify ESP32 to stop audio streaming."""
        self.running = False
        # Send stop command to ESP32
        if self.robot:
            try:
                self.robot.send_command("AUDIO_STOP")
            except Exception:
                pass

    def cleanup(self):
        """Cleanup resources after a live conversation ends."""
        self.running = False
        # Ensure ESP32 stops streaming
        if self.robot:
            try:
                self.robot.send_command("AUDIO_STOP")
            except Exception:
                pass
        # Close UDP sockets
        try:
            self.audio_in_socket.close()
        except Exception:
            pass
        try:
            self.audio_out_socket.close()
        except Exception:
            pass
        print("\n💬 Live conversation ended")

'''
    s2=before+new_block+after
    p.write_text(s2)
    print('Patched stop/cleanup block successfully')
