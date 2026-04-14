import React, { useEffect, useRef, useState } from 'react';
import { Hands } from '@mediapipe/hands';

export default function GestureController({ onSyncChange }) {
  const videoRef = useRef(null);
  const handsRef = useRef(null);
  const requestRef = useRef(null);
  const [streamActive, setStreamActive] = useState(false);

  useEffect(() => {
    let hands;
    let cameraStream;
    let processing = true;

    const initHands = async () => {
      try {
        hands = new Hands({
          locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/hands/${file}`,
        });

        hands.setOptions({
          maxNumHands: 1,
          modelComplexity: 1,
          minDetectionConfidence: 0.5,
          minTrackingConfidence: 0.5,
        });

        hands.onResults((results) => {
          if (!processing) return;
          if (results.multiHandLandmarks && results.multiHandLandmarks.length > 0) {
            const landmarks = results.multiHandLandmarks[0];
            const indexTip = landmarks[8];
            const dx = (indexTip.x - 0.5) * 20;
            const dy = -(indexTip.y - 0.5) * 20;
            const dz = (indexTip.z) * 50;

            window.dispatchEvent(new CustomEvent('luna-gesture-move', { 
              detail: { dx, dy, dz } 
            }));
            
            if (onSyncChange) onSyncChange(true);
          } else {
            if (onSyncChange) onSyncChange(false);
          }
        });

        handsRef.current = hands;
      } catch (e) {
        console.error('Hands init failed:', e);
      }
    };

    const startCamera = async () => {
      try {
        cameraStream = await navigator.mediaDevices.getUserMedia({ 
          video: { width: 640, height: 480, frameRate: 30 } 
        });
        if (videoRef.current) {
          videoRef.current.srcObject = cameraStream;
          videoRef.current.play();
          setStreamActive(true);
        }
      } catch (err) {
        console.warn('Camera access denied:', err);
      }
    };

    const processVideo = async () => {
      if (!processing) return;
      if (videoRef.current && videoRef.current.readyState === 4 && handsRef.current) {
        try {
          await handsRef.current.send({ image: videoRef.current });
        } catch (e) {}
      }
      requestRef.current = requestAnimationFrame(processVideo);
    };

    (async () => {
      await initHands();
      await startCamera();
      requestRef.current = requestAnimationFrame(processVideo);
    })();

    return () => {
      processing = false;
      cancelAnimationFrame(requestRef.current);
      if (cameraStream) {
        cameraStream.getTracks().forEach(track => track.stop());
      }
      if (hands) hands.close();
    };
  }, []); // Only once on mount

  return (
    <video 
      ref={videoRef} 
      style={{ 
        position: 'absolute', 
        bottom: 20, 
        right: 20, 
        width: 160, 
        height: 120, 
        transform: 'scaleX(-1)', // Mirror
        border: '1px solid #64b4ff',
        opacity: streamActive ? 0.3 : 0, // Ghost overlay
        borderRadius: '8px',
        pointerEvents: 'none',
        zIndex: 10
      }} 
    />
  );
}
