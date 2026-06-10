import React from 'react';

interface Props {
  headerText: string;
  headerFont: string;
  captionText: string;
  captionFont: string;
  hookText: string;
  hookFont: string;
  bgStyle: 'black' | 'brand' | 'blur' | 'white';
}

export const ClipPreview: React.FC<Props> = ({
  headerText, headerFont, captionText, captionFont, hookText, hookFont, bgStyle
}) => {
  const bgMap = {
    black: 'bg-black',
    brand: 'bg-slate-900',
    blur: 'bg-black/90 backdrop-blur-xl',
    white: 'bg-gray-50'
  };

  const isLight = bgStyle === 'white';
  const textColor = isLight ? 'text-gray-900' : 'text-white';
  const mutedColor = isLight ? 'text-gray-400' : 'text-white/40';
  const boxBg = isLight ? 'bg-gray-200 border-gray-300' : 'bg-white/10 border-white/20';

  return (
    <div className={`relative w-[280px] h-[500px] ${bgMap[bgStyle]} rounded-2xl overflow-hidden border border-gray-700 shadow-2xl mx-auto flex flex-col`}>
      
      {/* Hook — top, max 2 lines */}
      <div className="shrink-0 pt-4 px-3 text-center z-10 min-h-[60px] flex items-center justify-center">
        <span
          className={`${textColor} text-base font-bold leading-tight block line-clamp-2`}
          style={{
            fontFamily: hookFont,
            textShadow: isLight ? 'none' : '2px 2px 4px rgba(0,0,0,0.8), 0 0 10px rgba(0,0,0,0.5)',
            WebkitTextStroke: isLight ? '0' : '0.5px rgba(0,0,0,0.5)'
          }}
        >
          {hookText || 'YOUR HOOK TEXT'}
        </span>
      </div>

      {/* Video simulation */}
      <div className={`mx-3 mt-2 flex-1 min-h-0 rounded-xl border-2 border-dashed flex items-center justify-center ${boxBg}`}>
        <span className={`text-xs font-medium ${mutedColor}`}>Video Content Area</span>
      </div>

      {/* Header */}
      <div className="shrink-0 px-3 pt-3 text-center">
        <span
          className={`${textColor} text-sm font-bold block truncate`}
          style={{ fontFamily: headerFont }}
        >
          {headerText || 'Header Title'}
        </span>
      </div>

      {/* Caption */}
      <div className="shrink-0 px-3 pb-4 pt-2 text-center">
        <span
          className={`${textColor} text-[11px] leading-relaxed block line-clamp-3 px-2 py-1.5 rounded-md ${isLight ? 'bg-black/5' : 'bg-black/30'}`}
          style={{ fontFamily: captionFont }}
        >
          {captionText || 'Caption text preview'}
        </span>
      </div>
    </div>
  );
};

